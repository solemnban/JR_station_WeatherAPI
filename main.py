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

# ==============================
# LightGBM モデル
# ==============================
model = lgb.Booster(model_file="best_delay_lgbm.txt")
model_features = model.feature_name()

# ==============================
# 過去の遅延時間平均値
# ==============================
delay_stats = pd.read_csv("delay_weather_3hour_numeric.csv")
min_delay_mean = delay_stats["遅延時間（最小）"].dropna().mean()
max_delay_mean = delay_stats["遅延時間（最大）"].dropna().mean()

# ==============================
# 地点リスト
# ==============================
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

# ============================================================
# 1️⃣ /weather 天気予報 API
# ============================================================
@app.get("/weather")
def get_weather_endpoint():

    cache_key = "weather_forecast_cache"

    # キャッシュ確認
    try:
        cached = redis.get(cache_key)
        if cached:
            return {"source": "cache", "data": json.loads(cached)}
    except:
        pass

    results = []

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
            ow_data = res.json()

        except Exception as e:
            print(f"Error fetching {loc['name']}: {e}")
            continue

        forecasts = []

        for entry in ow_data.get("list", []):
            dt_jst = datetime.utcfromtimestamp(entry["dt"]).replace(
                tzinfo=timezone.utc
            ).astimezone(JST)

            forecasts.append({
                "datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M"),
                "weather": [w["main"] for w in entry.get("weather", [])],
                "rain_3h": entry.get("rain", {}).get("3h", 0),
                "snow_3h": entry.get("snow", {}).get("3h", 0),
                "temp": entry["main"]["temp"],
                "wind_speed": entry["wind"]["speed"],
                "wind_deg": entry["wind"]["deg"],
                "visibility": entry.get("visibility", 10000),
                "pressure": entry["main"].get("pressure", 1013),
                "humidity": entry["main"].get("humidity", 70),
            })

        results.append({
            "name": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "forecast": forecasts,
        })

    if not results:
        raise HTTPException(503, "No forecast available")

    try:
        redis.set(cache_key, json.dumps(results), ex=60*60)  # 1時間キャッシュ
    except:
        pass

    return {"source": "api", "data": results}


# ============================================================
# 2️⃣ /predict_delay 遅延予測 API
# ============================================================
@app.get("/predict_delay")
def predict_delay():

    # まず内部で天気 API を呼ぶ
    weather_res = get_weather_endpoint()
    weather_data = weather_res["data"]

    all_rows = []
    all_datetimes = []

    # ---------------------
    # 天気から特徴量生成
    # ---------------------
    for loc in weather_data:
        for f in loc["forecast"]:

            dt = f["datetime_jst"]
            weather_main = f["weather"]
            rain_3h = f["rain_3h"]
            snow_3h = f["snow_3h"]
            temp = f["temp"]
            wind_speed = f["wind_speed"]
            wind_deg = f["wind_deg"]
            visibility = f["visibility"]
            pressure = f["pressure"]
            humidity = f["humidity"]

            # --- 判定 ---
            is_typhoon = (
                wind_speed >= 20 or
                pressure <= 990 or
                "Tornado" in weather_main or
                "Squall" in weather_main
            )

            is_heavy_snow = (
                "Snow" in weather_main and snow_3h >= 5 and temp <= 2
            )

            is_heavy_rain = (
                "Rain" in weather_main and rain_3h >= 15
            )

            is_dense_fog = (
                visibility <= 200 or "Fog" in weather_main or "Mist" in weather_main
            )

            is_frost = (
                temp <= 3 and humidity >= 80
            )

            is_strong_wind = wind_speed >= 10

            row = {
                "台風": int(is_typhoon),
                "大雪": int(is_heavy_snow),
                "大雨": int(is_heavy_rain),
                "濃霧": int(is_dense_fog),
                "霜": int(is_frost),
                "強風": int(is_strong_wind),
                "precipitation": rain_3h / 3,
                "temperature": temp,
                "wind_speed": wind_speed,
                "wind_direction_deg": wind_deg,
                "wind_dir_sin": np.sin(np.deg2rad(wind_deg)),
                "wind_dir_cos": np.cos(np.deg2rad(wind_deg)),
            }

            all_rows.append(row)
            all_datetimes.append(dt)

    df = pd.DataFrame(all_rows)

    # モデルの列に合わせる
    for col in model_features:
        if col not in df.columns:
            df[col] = 0

    df = df[model_features]

    # 予測
    y_pred = model.predict(df)

    # 返すだけ（シンプル）
    results = [
        {"datetime": all_datetimes[i], "delay_probability": round(y_pred[i] * 100, 1)}
        for i in range(len(y_pred))
    ]

    return {"source": weather_res["source"], "data": results}

