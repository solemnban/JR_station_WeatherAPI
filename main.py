from fastapi import FastAPI, HTTPException
from upstash_redis import Redis
import requests
import os
import json
import pandas as pd
import numpy as np
import lightgbm as lgb
from datetime import datetime, timedelta, timezone

app = FastAPI(title="JR Delay Prediction API")

# ==============================
# 環境変数
# ==============================
UPSTASH_URL = os.getenv("UPSTASH_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# 学習済みモデル読み込み
model = lgb.Booster(model_file="best_delay_lgbm.txt")
model_features = model.feature_name()

# 過去の遅延時間平均値
delay_stats = pd.read_csv("delay_weather_3hour_numeric.csv")
min_delay_mean = delay_stats["遅延時間（最小）"].dropna().mean()
max_delay_mean = delay_stats["遅延時間（最大）"].dropna().mean()

# 対象地点
LOCATIONS = [
    {"name": "広島", "lat": 34.398, "lon": 132.461},
    {"name": "東広島", "lat": 34.416, "lon": 132.7},
    {"name": "本郷", "lat": 34.435, "lon": 132.918},
    {"name": "廿日市", "lat": 34.365, "lon": 132.19},
    {"name": "岩国", "lat": 34.155, "lon": 132.178},
    {"name": "下松", "lat": 34.01, "lon": 131.871},
    {"name": "山口", "lat": 34.161, "lon": 131.461},
    {"name": "宇部", "lat": 33.93, "lon": 131.278},
    {"name": "下関", "lat": 33.948, "lon": 130.925},
]

JST = timezone(timedelta(hours=9))

@app.get("/predict_delay")
def predict_delay():
    cache_key = "delay_prediction_cache"

    # キャッシュ確認
    try:
        cached = redis.get(cache_key)
        if cached:
            return {"source": "cache", "data": json.loads(cached)}
    except:
        pass

    all_rows = []
    all_datetimes = []

    for loc in LOCATIONS:
        try:
            res = requests.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "lat": loc["lat"],
                    "lon": loc["lon"],
                    "appid": OPENWEATHER_API_KEY,
                    "units": "metric",
                    "lang": "ja",
                },
                timeout=10,
            )
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"Error fetching data for {loc['name']}: {e}")
            continue

        for entry in data.get("list", []):
            dt_utc = datetime.utcfromtimestamp(entry["dt"]).replace(tzinfo=timezone.utc)
            dt_jst = dt_utc.astimezone(JST)
            all_datetimes.append(dt_jst.strftime("%Y-%m-%d %H:%M"))

            # =========================
            # 天気フラグ自動生成
            # =========================
            weather_main = [w["main"] for w in entry.get("weather", [])]

            row = {
                "台風": 1 if "Tornado" in weather_main or "Extreme" in weather_main else 0,
                "大雪": 1 if "Snow" in weather_main else 0,
                "大雨": 1 if "Rain" in weather_main and entry.get("rain", {}).get("3h", 0) > 10 else 0,
                "濃霧": 1 if "Fog" in weather_main else 0,
                "霜": 0,  # OpenWeatherMapには直接霜情報なし
                "強風": 1 if entry["wind"]["speed"] >= 10 else 0,  # m/sで10以上を強風と仮定
                "precipitation": entry.get("rain", {}).get("3h", 0) / 3,
                "temperature": entry["main"]["temp"],
                "wind_speed": entry["wind"]["speed"],
                "wind_direction_deg": entry["wind"]["deg"],
                "wind_dir_sin": np.sin(np.deg2rad(entry["wind"]["deg"])),
                "wind_dir_cos": np.cos(np.deg2rad(entry["wind"]["deg"])),
            }

            all_rows.append(row)

    if not all_rows:
        raise HTTPException(503, "No forecast data available")

    df_weather = pd.DataFrame(all_rows)
    df_weather["datetime_jst"] = all_datetimes

    # 学習時に存在したが欠損している列を補完
    for col in model_features:
        if col not in df_weather.columns:
            df_weather[col] = 0

    df_weather = df_weather[model_features]

    # 予測
    y_pred_prob = model.predict(df_weather)

    # 結果を日付ごとにまとめる
    results = []
    for i, prob in enumerate(y_pred_prob):
        results.append({
            "datetime": all_datetimes[i],
            "delay_probability": round(prob * 100, 1)
        })

    # キャッシュ保存（2時間）
    try:
        redis.set(cache_key, json.dumps(results), ex=2*60*60)
    except:
        pass

    return {"source": "api", "data": results}

