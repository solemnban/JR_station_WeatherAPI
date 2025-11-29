from fastapi import FastAPI, HTTPException
from upstash_redis import Redis
import requests
import os
import json
from datetime import datetime, timedelta, timezone
import time

app = FastAPI(title="JR Station Weather API")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
UPSTASH_URL = os.getenv("UPSTASH_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN")

redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

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


@app.get("/weather")
def get_weather():
    cache_key = "weather:hiroshima-region"
    lock_key = "lock:hiroshima-region"

    # ====== (1) Redis 障害を検知 ======
    try:
        cached = redis.get(cache_key)
    except:
        raise HTTPException(503, "Cache server unavailable")

    if cached:
        try:
            data = json.loads(cached)
        except:
            data = cached
        return {"source": "cache", "data": data}

    # ====== (2) ロックを取得（キャッシュミスが同時多発しないように） ======
    lock_acquired = False
    try:
        lock_acquired = redis.set(lock_key, "1", nx=True, ex=30)  # 30秒ロック
    except:
        raise HTTPException(503, "Cache server unavailable")

    # すでにロックがある = 他リクエストがAPI取得中 → 少し待つ
    if not lock_acquired:
        time.sleep(1.5)
        try:
            cached2 = redis.get(cache_key)
            if cached2:
                return {"source": "cache(delayed)", "data": json.loads(cached2)}
        except:
            raise HTTPException(503, "Cache server unavailable")
        raise HTTPException(429, "Please retry soon")  # ロック中

    # ====== (3) API 実行はここで1回だけ ======
    results = []
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
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

        forecasts = []
        for entry in data.get("list", []):
            dt_utc = datetime.utcfromtimestamp(entry["dt"]).replace(tzinfo=timezone.utc)
            dt_jst = dt_utc.astimezone(JST)
            if now_jst <= dt_jst <= tomorrow_end:
                forecasts.append({
                    "datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M"),
                    "temp": entry["main"]["temp"],
                    "rain_1h": entry.get("rain", {}).get("3h", 0) / 3,
                    "wind_speed": entry["wind"]["speed"],
                    "wind_deg": entry["wind"]["deg"],
                })

        results.append({
            "name": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "forecast": forecasts,
        })

    # ====== (4) キャッシュ保存 ======
    try:
        redis.set(cache_key, json.dumps(results), ex=2 * 60 * 60)
        redis.delete(lock_key)
    except:
        raise HTTPException(503, "Cache server unavailable")

    return {"source": "api", "data": results}
