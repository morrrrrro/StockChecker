"""シグナル精度サマリー算出

backtest.parquetから各スクリーンの勝率・平均リターンを算出する。
"""

import pandas as pd

from stock_report.db import DATA_DIR, save_parquet

BACKTEST_PATH = DATA_DIR / "signals" / "backtest.parquet"
ACCURACY_PATH = DATA_DIR / "signals" / "accuracy.parquet"

RETURN_PERIODS = [5, 10, 20]


def compute_accuracy() -> pd.DataFrame:
    """スクリーン別の精度統計を算出する"""
    try:
        bt = pd.read_parquet(BACKTEST_PATH)
    except FileNotFoundError:
        print("backtest.parquetが見つからない。先にbacktestを実行してね")
        return pd.DataFrame()

    rows = []
    for screen in bt["screen_type"].unique():
        sdf = bt[bt["screen_type"] == screen]
        row = {
            "screen_type": screen,
            "total_signals": len(sdf),
        }

        for period in RETURN_PERIODS:
            col = f"return_{period}d"
            valid = sdf[col].dropna()
            if valid.empty:
                row[f"win_rate_{period}d"] = None
                row[f"avg_return_{period}d"] = None
                row[f"median_return_{period}d"] = None
                continue

            row[f"win_rate_{period}d"] = round((valid > 0).mean() * 100, 1)
            row[f"avg_return_{period}d"] = round(valid.mean(), 2)
            row[f"median_return_{period}d"] = round(valid.median(), 2)

        # 全体の最大利益・最大損失
        all_returns = sdf[[f"return_{p}d" for p in RETURN_PERIODS]].values.flatten()
        all_returns = pd.Series(all_returns).dropna()
        row["max_return"] = round(all_returns.max(), 2) if not all_returns.empty else None
        row["max_loss"] = round(all_returns.min(), 2) if not all_returns.empty else None

        rows.append(row)

    return pd.DataFrame(rows)


def compute_accuracy_by_score_band() -> pd.DataFrame:
    """スコア帯別の勝率を算出する"""
    try:
        bt = pd.read_parquet(BACKTEST_PATH)
    except FileNotFoundError:
        return pd.DataFrame()

    bt = bt.dropna(subset=["composite_score"])
    if bt.empty:
        return pd.DataFrame()

    # スコア帯に分類
    bins = [0, 40, 50, 60, 70, 100]
    labels = ["0-40", "40-50", "50-60", "60-70", "70+"]
    bt["score_band"] = pd.cut(bt["composite_score"], bins=bins, labels=labels, include_lowest=True)

    rows = []
    for band in labels:
        band_df = bt[bt["score_band"] == band]
        if band_df.empty:
            continue

        row = {"score_band": band, "count": len(band_df)}
        for period in RETURN_PERIODS:
            col = f"return_{period}d"
            valid = band_df[col].dropna()
            row[f"win_rate_{period}d"] = round((valid > 0).mean() * 100, 1) if not valid.empty else None
            row[f"avg_return_{period}d"] = round(valid.mean(), 2) if not valid.empty else None

        rows.append(row)

    return pd.DataFrame(rows)


def run() -> None:
    """精度サマリーを算出して表示・保存する"""
    accuracy = compute_accuracy()
    if accuracy.empty:
        return

    save_parquet(accuracy, ACCURACY_PATH)

    print("=== スクリーン別精度 ===")
    print(accuracy.to_string(index=False))

    print("\n=== スコア帯別勝率 ===")
    score_band = compute_accuracy_by_score_band()
    if not score_band.empty:
        print(score_band.to_string(index=False))

    print(f"\n保存完了: {ACCURACY_PATH}")


if __name__ == "__main__":
    run()
