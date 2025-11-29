from fastapi import FastAPI, HTTPException
from upstash_redis import Redis
import requests
import os
import json
import pandas as pd
import numpy as np
import lightgbm as lgb
from datetime import datetime, timedelta, timezone
import time

app = FastAPI(title="JR Delay Prediction API")

# ==============================
# 環境変数
# ==============================
UPSTASH_URL = os.getenv("UPSTASH_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN")
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# 学習済みモデル読み込み
model = lgb.Booster(model_file="best_delay_lgbm.txt")

# 過去の遅延時間の平均値（目安用）
delay_stats = pd.read_csv("delay_weather_3hour_numeric.csv")
min_delay_mean = delay_stats["遅延時間（最小）"].dropna().mean()
max_delay_mean = delay_stats["遅延時間（最大）"].dropna().mean()

# モデル特徴量
model_features = model.feature_name()

# ==============================
# 天気予報APIのURL
# ==============================
WEATHER_API_URL = "https://jr-station-weatherapi.onrender.com/weather"

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

    # 天気API取得
    try:
        res = requests.get(WEATHER_API_URL, timeout=10)
        res.raise_for_status()
        weather_data = res.json()["data"]
    except Exception as e:
        raise HTTPException(503, f"Failed to fetch weather data: {e}")

    # JSON -> データフレーム
    rows = []
    datetimes = []

    for station in weather_data:
        for f in station["forecast"]:
            dt = f["datetime_jst"]
            datetimes.append(dt)

            row = {
                "台風": 1 if f.get("typhoon", 0) else 0,
                "大雪": 1 if f.get("heavy_snow", 0) else 0,
                "大雨": 1 if f.get("heavy_rain", 0) else 0,
                "濃霧": 1 if f.get("dense_fog", 0) else 0,
                "霜": 1 if f.get("frost", 0) else 0,
                "強風": 1 if f.get("strong_wind", 0) else 0,
                "precipitation": f["rain_1h"],
                "temperature": f["temp"],
                "wind_speed": f["wind_speed"],
                "wind_direction_deg": f["wind_deg"],
                "wind_dir_sin": np.sin(np.deg2rad(f["wind_deg"])),
                "wind_dir_cos": np.cos(np.deg2rad(f["wind_deg"])),
            }
            rows.append(row)

    df_weather = pd.DataFrame(rows)
    df_weather["datetime_jst"] = datetimes

    # モデル列に合わせる
    for col in model_features:
        if col not in df_weather.columns:
            df_weather[col] = 0
    df_weather = df_weather[model_features]

    # 予測
    y_pred_prob = model.predict(df_weather)

    # 日付ごとの結果にまとめる
    results = []
    for i, prob in enumerate(y_pred_prob):
        dt_str = datetimes[i]
        pct = round(prob * 100, 1)
        results.append({
            "datetime": dt_str,
            "delay_probability": pct
        })

    # キャッシュ保存（2時間）
    try:
        redis.set(cache_key, json.dumps(results), ex=2*60*60)
    except:
        pass

    return {"source": "api", "data": results}
