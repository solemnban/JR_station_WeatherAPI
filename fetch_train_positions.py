import os
import csv
import sys
import requests
from datetime import datetime

# ==========================================
# ⚙️ 設定と初期化
# ==========================================
CSV_FILE_PATH = "data/train_logs.csv"
os.makedirs(os.path.dirname(CSV_FILE_PATH), exist_ok=True)

# 📊 列車データの標準的な7カラム
CSV_HEADERS = [
    "timestamp", "train_no", "station_code", "direction", 
    "delay_min", "congestion", "delay_cause"
]

# 初回実行時のみヘッダーを書き込み
if not os.path.exists(CSV_FILE_PATH):
    with open(CSV_FILE_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
TRAIN_URL = "https://train-guide.westjr.co.jp/api/v3/sanyo2.json"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
}

# ==========================================
# 📥 1. 列車データの取得
# ==========================================
try:
    response = requests.get(TRAIN_URL, headers=HTTP_HEADERS, timeout=15)
    response.raise_for_status()
    train_data = response.json()
except Exception as e:
    print(f"[{current_timestamp}] 警告: JR西日本サーバーへの接続失敗: {e}")
    sys.exit(0)

# 🌟 JR西日本が発表している全体の遅延理由（notice）をルート階層から取得
# 例: "大雨のため、一部列車に遅延が..."。発表が無い場合は空文字やNoneになるため安全に処理
raw_notice = train_data.get("notice")
if raw_notice:
    # 改行や不要な空白を除去して1行のクリーンなテキストにする
    global_delay_cause = raw_notice.replace("\n", " ").replace("\r", "").strip()
else:
    global_delay_cause = "平常"

# ==========================================
# 🔄 2. 列車データの処理と結合
# ==========================================
parsed_records = []
trains_list = train_data.get("trains", [])

if not trains_list:
    print(f"[{current_timestamp}] 走行中の列車データが0件のためスキップします。")
    sys.exit(0)

for t in trains_list:
    try:
        train_no = t.get("no", "Unknown")
        pos_raw = t.get("pos", "####_####")
        station_code = pos_raw.split("_")[0] if pos_raw else "####"
        direction = t.get("direction", 0)
        
        delay_min = t.get("delayMinutes", 0)
        if delay_min is None:
            delay_min = 0

        # 🌟 【重要修正】
        # その列車が「実際に1分以上遅延している」場合のみ、全体のお知らせ（遅延理由）を記録
        # 遅延していない（0分）なら、一律で「平常」として保存
        if delay_min > 0:
            actual_cause = global_delay_cause if global_delay_cause != "平常" else "一部列車遅延"
        else:
            actual_cause = "平常"

        # 混雑度はAPI側に無いため一律0で固定
        congestion = 0

        parsed_records.append([
            current_timestamp, train_no, station_code, direction, 
            delay_min, congestion, actual_cause
        ])
    except Exception:
        continue

# ==========================================
# 💾 3. CSVへの追記保存
# ==========================================
if parsed_records:
    with open(CSV_FILE_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(parsed_records)
        f.flush()
        os.fsync(f.fileno())
    print(f"[{current_timestamp}] 列車位置ログの修正版保存に成功しました（遅延理由を正常化）。")
