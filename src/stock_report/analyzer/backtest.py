"""過去シグナルのバックテスト

既存の株価データを使って、各営業日にスクリーニングを遡及実行し、
N日後のリターンを計測する。
"""

from datetime import date, timedelta

import duckdb
import pandas as pd

from stock_report.analyzer.scoring import compute_scores
from stock_report.analyzer.screener import screen_a, screen_b, screen_c, detect_convergence
from stock_report.db import DATA_DIR, save_parquet

BACKTEST_PATH = DATA_DIR / "signals" / "backtest.parquet"

# リターン計測期間（営業日数）
RETURN_PERIODS = [5, 10, 20]


def _get_trading_dates(start: date, end: date) -> list[date]:
    """期間内の営業日リストを取得する（株価データが存在する日のみ）"""
    df = duckdb.sql(f"""
        SELECT DISTINCT date
        FROM read_parquet('data/prices/*.parquet', union_by_name=True)
        WHERE date >= '{start}' AND date <= '{end}'
        ORDER BY date
    """).fetchdf()
    return [d.date() for d in pd.to_datetime(df["date"])]


def _get_future_prices(ticker: str, signal_date: date, max_days: int = 30) -> dict:
    """シグナル日以降のN営業日後の終値を取得する"""
    df = duckdb.sql(f"""
        SELECT date, close,
               ROW_NUMBER() OVER (ORDER BY date) as day_num
        FROM read_parquet('data/prices/*.parquet', union_by_name=True)
        WHERE ticker = '{ticker}' AND date > '{signal_date}'
        ORDER BY date
        LIMIT {max_days}
    """).fetchdf()

    result = {}
    for period in RETURN_PERIODS:
        row = df[df["day_num"] == period]
        result[f"close_{period}d"] = row["close"].iloc[0] if not row.empty else None
    return result


def run_backtest(start_date: date | None = None, end_date: date | None = None, sample_interval: int = 5) -> None:
    """バックテストを実行する

    sample_interval: N営業日ごとにスクリーニング実行（全営業日は重いため）
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=25)  # 20営業日後のリターンが必要
    if start_date is None:
        start_date = end_date - timedelta(days=180)  # 6ヶ月

    trading_dates = _get_trading_dates(start_date, end_date)

    # サンプリング（N日ごと）
    sampled_dates = trading_dates[::sample_interval]
    print(f"バックテスト: {start_date} ~ {end_date}")
    print(f"  営業日数: {len(trading_dates)}, サンプル日数: {len(sampled_dates)} (間隔: {sample_interval}日)")

    all_results = []

    for i, test_date in enumerate(sampled_dates):
        print(f"  [{i+1}/{len(sampled_dates)}] {test_date}...", end=" ")

        # スコアリング実行
        scored = compute_scores(test_date)
        if scored.empty:
            print("skip")
            continue

        # 3スクリーン実行
        results = []
        for screen_fn in [screen_a, screen_b, screen_c]:
            result = screen_fn(scored)
            results.append(result)
        signals = pd.concat(results, ignore_index=True)

        # 収束シグナル
        convergence = detect_convergence(signals)
        if not convergence.empty:
            signals = pd.concat([signals, convergence], ignore_index=True)

        if signals.empty:
            print("0 signals")
            continue

        # 各シグナルのN日後リターンを計測
        signal_count = 0
        for _, sig in signals.iterrows():
            ticker = sig["ticker"]
            close_at_signal = sig.get("close")
            if pd.isna(close_at_signal) or close_at_signal is None or close_at_signal <= 0:
                continue

            future = _get_future_prices(ticker, test_date)

            row = {
                "signal_date": test_date,
                "ticker": ticker,
                "screen_type": sig["screen_type"],
                "composite_score": sig.get("composite_score"),
                "close_at_signal": close_at_signal,
            }

            for period in RETURN_PERIODS:
                future_close = future.get(f"close_{period}d")
                row[f"close_{period}d"] = future_close
                if future_close and close_at_signal:
                    row[f"return_{period}d"] = (future_close - close_at_signal) / close_at_signal * 100
                else:
                    row[f"return_{period}d"] = None

            all_results.append(row)
            signal_count += 1

        print(f"{signal_count} signals")

    if not all_results:
        print("バックテスト結果なし")
        return

    df = pd.DataFrame(all_results)
    save_parquet(df, BACKTEST_PATH)
    print(f"\n保存完了: {BACKTEST_PATH} ({len(df)}レコード)")

    # 簡易サマリー表示
    for screen in df["screen_type"].unique():
        screen_df = df[df["screen_type"] == screen]
        for period in RETURN_PERIODS:
            col = f"return_{period}d"
            valid = screen_df[col].dropna()
            if valid.empty:
                continue
            win_rate = (valid > 0).mean() * 100
            avg_ret = valid.mean()
            print(f"  {screen} {period}d: 勝率={win_rate:.1f}% 平均リターン={avg_ret:+.2f}% (n={len(valid)})")


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    run_backtest(sample_interval=interval)
