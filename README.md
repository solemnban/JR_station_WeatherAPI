# JR Delay Prediction API (JR_station_WeatherAPI)

山陽本線（広島〜下関間）の主要地点における気象予報データを基に、LightGBM（機械学習モデル）を用いて列車の遅延確率を予測するFastAPIアプリケーションです。

## 📌 概要

本プロジェクトは、JR山陽本線の運行データと気象データの相関関係に関する研究・学習を目的としています。
OpenWeatherMapから取得した3時間ごとの天気予報データを特徴量（大雨、強風、台風、気温など）に変換し、事前に学習させたLightGBMモデル（`best_delay_lgbm.txt`）に入力することで、未来の遅延確率（%）を算出します。

## 🛠️ 機能

- **`/weather` (GET):** 指定された山陽本線の9地点（広島、東広島、本郷、廿日市、岩国、下松、山口、宇部、下関）の5日間（3時間刻み）の天気予報を取得。Upstash Redisによる1時間のキャッシュ機能を搭載。
- **`/predict_delay` (GET):** 各地点の予報データから特徴量を自動抽出し、時系列順に並んだ遅延確率の予測結果を返却。

## 📂 必要なファイル（リポジトリ構成）

正常に動作させるために、以下のファイルがリポジトリ内に配置されている必要があります。

- `main.py` (本プログラム)
- `best_delay_lgbm.txt` (学習済みのLightGBMモデルファイル)
- `delay_weather_3hour_numeric.csv` (過去の遅延統計データ)

## ⚙️ 動作環境・環境変数

実行には以下の環境変数（Secret）の設定が必要です。

```env
OPENWEATHER_API_KEY=your_openweather_api_key
UPSTASH_URL=your_upstash_redis_url
UPSTASH_TOKEN=your_upstash_redis_token
