import os
import csv
import sys
from datetime import datetime
import westjr

# ==========================================
# ⚙️ 設定と初期化
# ==========================================
CSV_FILE_PATH = "data/train_logs.csv"
os.makedirs(os.path.dirname(CSV_FILE_PATH), exist_ok=True)

# 設計書通りのカラムに固定
CSV_HEADERS = ["timestamp", "train_no", "station_code", "direction", "delay_min", "congestion", "delay_cause"]

# CSVがなければヘッダー付きで新規作成
if not os.path.exists(CSV_FILE_PATH):
    with open(CSV_FILE_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

# 山陽本線（広島・山口エリア：sanyo2）を指定して初期化
jr = westjr.WestJR(line="sanyo2", area="hiroshima")

# ==========================================
# 📥 1. データの取得と整形
# ==========================================
try:
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # APIリクエスト
    trains_res = jr.get_trains()
    trains_list = trains_res.trains if hasattr(trains_res, "trains") else []
    
    monitor_res = jr.get_train_monitor_info()
    monitor_trains = monitor_res.trains if hasattr(monitor_res, "trains") else {}
    
    traffic_info = jr.get_traffic_info()

except Exception as api_err:
    print(f"[{datetime.now()}] API取得フェーズで致命的なエラー: {api_err}", file=sys.stderr)
    sys.exit(1)

# --- 運行情報のパース ---
delay_cause = "平常"
try:
    if hasattr(traffic_info, "lines") and traffic_info.lines:
        target_line = "sanyo2"
        if target_line in traffic_info.lines:
            sanyo_info = traffic_info.lines[target_line]
            delay_cause = getattr(sanyo_info, "cause", None) or getattr(sanyo_info, "status", None) or "一部列車遅延"
except Exception:
    delay_cause = "データパースエラー"

# ==========================================
# 🔄 2. 列車ごとのレコード結合処理
# ==========================================
parsed_records = []

for t in trains_list:
    try:
        train_no = t.no
        station_code = t.pos.split("_")[0] if t.pos else "####"
        direction = t.direction
        delay_min = t.delayMinutes if t.delayMinutes is not None else 0

        # --- 混雑情報のパース ---
        congestion = 0
        try:
            if train_no in monitor_trains and monitor_trains[train_no]:
                first_car_group = monitor_trains[train_no][0]
                if hasattr(first_car_group, "cars") and len(first_car_group.cars) > 0:
                    congestion = first_car_group.cars[0].congestion
        except Exception:
            congestion = 0

        parsed_records.append([
            current_timestamp, train_no, station_code, direction, delay_min, congestion, delay_cause
        ])
    except Exception as row_err:
        print(f"列車個別データのパーススキップ ({getattr(t, 'no', 'Unknown')}): {row_err}", file=sys.stderr)
        continue

# ==========================================
# 💾 3. 物理ディスクへの即時同期と書き込み
# ==========================================
if parsed_records:
    with open(CSV_FILE_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(parsed_records)
        
        # 仮想環境のディスクへ即時フラッシュ
        f.flush()
        os.fsync(f.fileno())
    print(f"[{current_timestamp}] {len(parsed_records)} 件の列車レコードを同期保存しました。")
else:
    print(f"[{current_timestamp}] 走行中の列車データが0件のためスキップしました。")
