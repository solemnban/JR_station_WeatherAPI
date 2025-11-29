from fastapi import FastAPI, HTTPException
from upstash_redis import Redis
import requests
import os
import json
from datetime import datetime, timedelta, timezone
import lightgbm as lgb
import pandas as pd
import numpy as np

app = FastAPI(title="JR Station Delay Prediction API")

# 環境変数
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
UPSTASH_URL = os.getenv("UPSTASH_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN")

# Redis クライアント
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# 学習済みモデルロード
MODEL_FILE = "best_delay_lgbm.txt"
model = lgb.Booster(model_file=MODEL_FILE)

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
    now_jst = datetime.now(JST)
    cache_key = f"delay_prediction:{now_jst.strftime('%Y-%m-%d-%H')}"

    # キャッシュ確認
    try:
        cached = redis.get(cache_key)
        if cached:
            return {"source": "cache", "predictions": json.loads(cached)}
    except:
        pass

    # 予測用データ作成
    all_forecasts = []
    tomorrow_end = (now_jst + timedelta(days=1)).replace(hour=23, minute=59, second=59)

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
            if now_jst <= dt_jst <= tomorrow_end:
                all_forecasts.append({
                    "datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M"),
                    "precipitation": entry.get("rain", {}).get("3h", 0) / 3,
                    "temperature": entry["main"]["temp"],
                    "wind_speed": entry["wind"]["speed"],
                    "wind_direction_deg": entry["wind"]["deg"],
                    # wind_dir_sin / cos 計算
                    "wind_dir_sin": np.sin(np.deg2rad(entry["wind"]["deg"])),
                    "wind_dir_cos": np.cos(np.deg2rad(entry["wind"]["deg"])),
                })

    if not all_forecasts:
        raise HTTPException(500, "No forecast data available")

    # DataFrame 化
    df = pd.DataFrame(all_forecasts)

    # 運休フラグは 0 に固定（学習時と同じ列順に注意）
    df["運休フラグ_正常"] = 1
    df["運休フラグ_終日運転取りやめ"] = 0
    # 文字列列はモデル学習時に one-hot 化済みなら追加列を作成
    for col in ["wind_direction_北北東","wind_direction_北北西","wind_direction_北東","wind_direction_北西",
                "wind_direction_南","wind_direction_南南東","wind_direction_南南西","wind_direction_南東",
                "wind_direction_南西","wind_direction_東","wind_direction_東北東","wind_direction_東南東",
                "wind_direction_西","wind_direction_西北西","wind_direction_西南西","wind_direction_静穏",
                "weather_location_Higashihiroshima","weather_location_Hiroshima","weather_location_Hongo",
                "weather_location_Iwakuni","weather_location_Shimonoseki","weather_location_Ube","weather_location_Yamaguchi"]:
        if col not in df.columns:
            df[col] = 0

    # 学習時と同じ列順に並べる（必須）
    model_cols = model.feature_name()
    df = df[model_cols]

    # 予測
    pred_probs = model.predict(df)

    # 文章化
    results = []
    for i, row in df.iterrows():
        date_str = all_forecasts[i]["datetime_jst"]
        prob = pred_probs[i]
        if prob > 0.5:
            text = f"{date_str} は {prob*100:.1f}% の確率で遅延が発生する可能性があります。"
        else:
            text = f"{date_str} は遅延の可能性は低いです。"
        results.append(text)

    # キャッシュ保存（TTL: 3時間）
    try:
        redis.set(cache_key, json.dumps(results), ex=3*60*60)
    except:
        pass

    return {"source": "api", "predictions": results}

