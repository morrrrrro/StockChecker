"""株価データ取得（yfinance OHLCV）

全東証 + 米国主要株 + ETFの株価を一括取得する。
大量銘柄はバッチ分割して取得する。
"""

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR, append_to_monthly_parquet
from stock_report.universe import get_all_tickers

# yfinance.downloadの1バッチあたりの最大銘柄数
BATCH_SIZE = 500


def fetch_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """yfinanceで株価OHLCVを一括取得し、整形したDataFrameを返す

    大量銘柄はBATCH_SIZE件ずつに分割して取得する。
    """
    print(f"株価取得中... {len(tickers)}銘柄 ({start} ~ {end})")

    all_rows = []
    for batch_start in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  バッチ {batch_num}/{total_batches} ({len(batch)}銘柄)")

        try:
            raw = yf.download(batch, start=str(start), end=str(end), group_by="ticker", threads=True)
        except Exception as e:
            print(f"  バッチ{batch_num}エラー: {e}")
            continue

        if raw.empty:
            continue

        rows = _parse_download_result(raw, batch)
        all_rows.extend(rows)

    if not all_rows:
        print("データが取得できなかった")
        return pd.DataFrame()

    result = pd.concat(all_rows, ignore_index=True)
    print(f"  取得完了: {len(result)}行 ({result['ticker'].nunique()}銘柄)")
    return result


def _parse_download_result(raw: pd.DataFrame, tickers: list[str]) -> list[pd.DataFrame]:
    """yfinance.downloadの結果をパースする"""
    rows = []
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                ticker_data = raw
            else:
                ticker_data = raw[ticker]

            if ticker_data.empty:
                continue

            df = ticker_data.reset_index()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.rename(columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })
            df["ticker"] = ticker
            df = df[["date", "ticker", "open", "high", "low", "close", "volume"]]
            df = df.dropna(subset=["close"])
            rows.append(df)
        except (KeyError, TypeError):
            continue
    return rows


def run(days: int = 400, category: str | None = None) -> None:
    """株価データを取得してParquetに保存する

    category: "tse", "us", "etf" または None（全て）
    """
    all_tickers = get_all_tickers()
    end = date.today()
    start = end - timedelta(days=days)

    if category:
        tickers = all_tickers.get(category, [])
        print(f"カテゴリ: {category}")
    else:
        # 全カテゴリ統合
        tickers = []
        for lst in all_tickers.values():
            tickers.extend(lst)

    if not tickers:
        print("対象銘柄なし")
        return

    df = fetch_prices(tickers, start, end)
    if df.empty:
        print("保存するデータなし")
        return

    prices_dir = DATA_DIR / "prices"
    append_to_monthly_parquet(df, prices_dir)
    print(f"保存完了: {prices_dir}")


if __name__ == "__main__":
    import sys
    # 引数でカテゴリ指定: python -m stock_report.fetcher.price tse
    cat = sys.argv[1] if len(sys.argv) > 1 else None
    run(category=cat)
