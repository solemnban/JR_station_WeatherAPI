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

CSV_HEADERS = ["timestamp", "train_no", "station_code", "direction", "delay_min", "congestion", "delay_cause"]

if not os.path.exists(CSV_FILE_PATH):
    with open(CSV_FILE_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

# 🌐 タイムスタンプ
current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

jr = westjr.WestJR(line="sanyo2", area="hiroshima")

# ==========================================
# 📥 1. データの取得と超安全なエラーハンドリング
# ==========================================

# --- 列車位置情報の取得 ---
try:
    trains_res = jr.get_trains()
    if not trains_res or not hasattr(trains_res, "trains") or not trains_res.trains:
        print(f"[{current_timestamp}] 走行中の列車データが0件のため、この5分は書き込みをスキップします。")
        sys.exit(0)
    trains_list = trains_res.trains
except Exception as api_err:
    print(f"[{current_timestamp}] 警告: JR西日本APIの内部データ異常を検知しました。")
    print(f"詳細エラー: {api_err}")
    print("システムを保護するため、今回の収集は安全にスキップ（正常終了）し、5分後の次回に期待します。")
    sys.exit(0)

# --- 混雑情報の取得 ---
try:
    monitor_res = jr.get_train_monitor_info()
    monitor_trains = monitor_res.trains if (monitor_res and hasattr(monitor_res, "trains")) else {}
except Exception as api_err:
    print(f"[{current_timestamp}] 警告: 混雑情報APIの取得に失敗 (スキップ): {api_err}", file=sys.stderr)
    monitor_trains = {}

# --- 運行情報の取得（路線全体の遅延理由を取得） ---
try:
    traffic_info = jr.get_traffic_info()
    global_delay_cause = "平常"
    if traffic_info and hasattr(traffic_info, "lines") and traffic_info.lines:
        target_line = "sanyo2"
        if target_line in traffic_info.lines:
            sanyo_info = traffic_info.lines[target_line]
            # 原因(cause) または 状態(status) を取得、どちらも無ければ "一部列車遅延"
            global_delay_cause = getattr(sanyo_info, "cause", None) or getattr(sanyo_info, "status", None) or "一部列車遅延"
except Exception as api_err:
    print(f"[{current_timestamp}] 警告: 運行情報APIの取得に失敗: {api_err}", file=sys.stderr)
    global_delay_cause = "平常"

# ==========================================
# 🔄 2. 列車ごとのレコード結合処理
# ==========================================
parsed_records = []

for t in trains_list:
    try:
        if not t or not hasattr(t, "no"):
            continue
            
        train_no = t.no
        station_code = t.pos.split("_")[0] if getattr(t, "pos", None) else "####"
        direction = getattr(t, "direction", 0)
        delay_min = getattr(t, "delayMinutes", 0)
        if delay_min is None:
            delay_min = 0

        # 🌟【ロジック修正箇所】
        # その列車が実際に遅延（1分以上）している場合のみ、全体の遅延理由をセット
        # 遅延していない（0分）なら、路線全体で何か起きていてもその列車自体は「平常」
        if delay_min > 0:
            actual_cause = global_delay_cause if global_delay_cause != "平常" else "一部列車遅延"
        else:
            actual_cause = "平常"

        # --- 混雑情報のパース ---
        congestion = 0
        try:
            if train_no in monitor_trains and monitor_trains[train_no]:
                first_car_group = monitor_trains[train_no][0]
                if first_car_group and hasattr(first_car_group, "cars") and first_car_group.cars:
                    congestion = first_car_group.cars[0].congestion
        except Exception:
            congestion = 0

        parsed_records.append([
            current_timestamp, train_no, station_code, direction, delay_min, congestion, actual_cause
        ])
    except Exception as row_err:
        print(f"列車個別データのパーススキップ: {row_err}", file=sys.stderr)
        continue

# ==========================================
# 💾 3. 物理ディスクへの書き込み
# ==========================================
if parsed_records:
    with open(CSV_FILE_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(parsed_records)
        f.flush()
        os.fsync(f.fileno())
    print(f"[{current_timestamp}] {len(parsed_records)} 件の列車レコードを同期保存しました（遅延理由修正版）。")
else:
    print(f"[{current_timestamp}] 保存すべきデータがありませんでした。")
