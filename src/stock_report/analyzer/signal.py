"""シグナルライフサイクル管理

スクリーニング結果を日次追跡し、状態遷移を管理する。
新規 → 強化中 → 安定 → 減衰中 → 消失
"""

import json
from datetime import date

import pandas as pd

from stock_report.db import DATA_DIR, save_parquet

LIFECYCLE_PATH = DATA_DIR / "signals" / "lifecycle.parquet"


def load_lifecycle() -> pd.DataFrame:
    """既存のライフサイクルデータを読み込む"""
    try:
        return pd.read_parquet(LIFECYCLE_PATH)
    except FileNotFoundError:
        return pd.DataFrame(columns=[
            "ticker", "signal_type", "first_detected", "current_state",
            "days_active", "score_history", "last_updated",
        ])


def update_lifecycle(signals: pd.DataFrame, target_date: date | None = None) -> pd.DataFrame:
    """シグナルのライフサイクルを更新する

    - 新しいシグナル → "new"
    - 前回も存在 + スコア上昇 → "strengthening"
    - 前回も存在 + スコア横ばい → "stable"
    - 前回は存在 + 今回消失 → "fading"
    - "fading"が2日以上続く → 削除
    """
    if target_date is None:
        target_date = date.today()

    lifecycle = load_lifecycle()
    today_str = str(target_date)

    # 今日のシグナル（convergence以外）のキー
    today_keys = set()
    if not signals.empty:
        today_signals = signals[signals["screen_type"] != "convergence"]
        today_keys = set(zip(today_signals["ticker"], today_signals["screen_type"]))

    new_rows = []

    # 既存シグナルの更新
    for _, row in lifecycle.iterrows():
        key = (row["ticker"], row["signal_type"])
        if key in today_keys:
            # 今日も存在するシグナル
            today_signal = signals[
                (signals["ticker"] == row["ticker"]) & (signals["screen_type"] == row["signal_type"])
            ].iloc[0]

            score = today_signal.get("composite_score", 0)
            history = json.loads(row["score_history"]) if row["score_history"] else []
            history.append({"date": today_str, "score": round(score, 1)})

            # 状態判定
            prev_score = history[-2]["score"] if len(history) >= 2 else 0
            if score > prev_score * 1.05:
                state = "strengthening"
            elif row["current_state"] == "new" and row["days_active"] <= 2:
                state = "new"
            else:
                state = "stable"

            new_rows.append({
                "ticker": row["ticker"],
                "signal_type": row["signal_type"],
                "first_detected": row["first_detected"],
                "current_state": state,
                "days_active": row["days_active"] + 1,
                "score_history": json.dumps(history[-30:]),  # 直近30日分のみ保持
                "last_updated": today_str,
            })
            today_keys.discard(key)
        else:
            # 今日消失したシグナル
            if row["current_state"] == "fading":
                # 2日以上fadingなら削除（行を追加しない）
                if row["days_active"] <= 1:
                    row_dict = row.to_dict()
                    row_dict["days_active"] += 1
                    row_dict["last_updated"] = today_str
                    new_rows.append(row_dict)
            else:
                row_dict = row.to_dict()
                row_dict["current_state"] = "fading"
                row_dict["days_active"] += 1
                row_dict["last_updated"] = today_str
                new_rows.append(row_dict)

    # 新規シグナルの追加
    for ticker, signal_type in today_keys:
        today_signal = signals[
            (signals["ticker"] == ticker) & (signals["screen_type"] == signal_type)
        ].iloc[0]
        score = today_signal.get("composite_score", 0)

        new_rows.append({
            "ticker": ticker,
            "signal_type": signal_type,
            "first_detected": today_str,
            "current_state": "new",
            "days_active": 1,
            "score_history": json.dumps([{"date": today_str, "score": round(score, 1)}]),
            "last_updated": today_str,
        })

    result = pd.DataFrame(new_rows) if new_rows else pd.DataFrame(columns=lifecycle.columns)
    return result


def run(target_date: date | None = None) -> None:
    """シグナルライフサイクルを更新する"""
    if target_date is None:
        target_date = date.today()

    # 当日のシグナルを読み込み
    signal_path = DATA_DIR / "signals" / f"{target_date}.parquet"
    try:
        signals = pd.read_parquet(signal_path)
    except FileNotFoundError:
        print(f"シグナルファイルなし: {signal_path}")
        signals = pd.DataFrame()

    print("シグナルライフサイクル更新中...")
    lifecycle = update_lifecycle(signals, target_date)
    save_parquet(lifecycle, LIFECYCLE_PATH)

    # 状態別の集計
    if not lifecycle.empty:
        state_counts = lifecycle["current_state"].value_counts()
        for state, count in state_counts.items():
            print(f"  {state}: {count}件")
    else:
        print("  アクティブなシグナルなし")

    print(f"  保存完了: {LIFECYCLE_PATH}")


if __name__ == "__main__":
    run()
