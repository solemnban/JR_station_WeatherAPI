from fastapi import FastAPI
from upstash_redis import Redis
import requests
import os
import json
from datetime import datetime, timedelta, timezone

app = FastAPI(title="JR station Weather API")

# === 環境変数 ===
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
UPSTASH_URL = os.getenv("UPSTASH_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN")

redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# === 取得対象地点 ===
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
    """
    広島〜山口周辺9地点の天気予報を返す。
    ・今日〜翌日23:59までのデータ
    ・キャッシュ：2時間
    ・出力フォーマットはAPI取得時とキャッシュ取得時で完全一致
    """
    cache_key = "weather:hiroshima-region"
    cached = redis.get(cache_key)

    # === キャッシュが存在すれば返す ===
    if cached:
        try:
            data = json.loads(cached)
            return {"source": "cache", "data": data}
        except Exception:
            # JSONデコードできない場合はそのまま返す
            return {"source": "cache", "data": cached}

    # === キャッシュがなければAPIから取得 ===
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
            # APIエラー時はスキップ（もしくは空データで埋める）
            print(f"Error fetching data for {loc['name']}: {e}")
            continue

        # 期間内データを抽出
        forecasts = []
        for entry in data.get("list", []):
            dt_utc = datetime.utcfromtimestamp(entry["dt"]).replace(tzinfo=timezone.utc)
            dt_jst = dt_utc.astimezone(JST)

            if now_jst <= dt_jst <= tomorrow_end:
                forecasts.append({
                    "datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M"),
                    "temp": entry["main"]["temp"],
                    "rain_1h": entry.get("rain", {}).get("3h", 0) / 3,  # 3h→1h換算
                    "wind_speed": entry["wind"]["speed"],
                    "wind_deg": entry["wind"]["deg"],
                    "weather": entry["weather"][0]["description"],
                })

        results.append({
            "name": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "forecast": forecasts,
        })

    # === Redisに保存（2時間キャッシュ） ===
    redis.set(cache_key, json.dumps(results), ex=2 * 60 * 60)

    return {"source": "api", "data": results}
