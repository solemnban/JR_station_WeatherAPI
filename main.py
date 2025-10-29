from fastapi import FastAPI
from fastapi.responses import JSONResponse
import requests
from upstash_redis import Redis
import os

app = FastAPI(title="JR station Weather API")

# === 環境変数 ===
OPENWEATHER_API_KEY = os.getenv("1afb66f10a65a47c27fbf31becbdf6b0")
UPSTASH_URL = os.getenv("https://real-lioness-6459.upstash.io")
UPSTASH_TOKEN = os.getenv("ARk7AAImcDIwYTJjMWU1YWExNDI0ZjUwYTJhMGJhM2Q4ZTk0OGJlMXAyNjQ1OQ")

# === Upstash Redis 接続 ===
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# === 対象地点 ===
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

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/forecast"

@app.get("/weather")
def get_weather():
    """9地点の天気予報をキャッシュ付きで取得"""
    cache_key = "weather:hiroshima-region"
    cached_data = redis.get(cache_key)

    # キャッシュヒット
    if cached_data:
        print("🔹 Using cached weather data")
        return JSONResponse(content={"source": "cache", "data": cached_data})

    print("⚡ Fetching data from OpenWeather API")
    results = []

    for loc in LOCATIONS:
        params = {
            "lat": loc["lat"],
            "lon": loc["lon"],
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            "lang": "ja",
        }

        res = requests.get(OPENWEATHER_URL, params=params)
        data = res.json()

        # 最新の3時間予報データ
        forecast = data["list"][0]

        # 降水量（3時間分を1時間あたりに換算）
        rain_3h = forecast.get("rain", {}).get("3h", 0)
        rain_1h = round(rain_3h / 3, 2)

        results.append({
            "name": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "temp": forecast["main"]["temp"],
            "rain_1h": rain_1h,
            "wind_speed": forecast["wind"]["speed"],
            "wind_deg": forecast["wind"]["deg"],
            "timestamp": forecast["dt_txt"]
        })

    # キャッシュを3時間保持
    redis.set(cache_key, results, ex=3 * 60 * 60)

    return JSONResponse(content={"source": "api", "data": results})

@app.get("/")
def home():
    return {"message": "✅ FastAPI + Upstash + OpenWeather API ready!"}
