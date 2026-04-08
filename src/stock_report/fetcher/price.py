"""株価データ取得（yfinance OHLCV）"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR, append_to_monthly_parquet

# watchlist.tomlの読み込み
CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "watchlist.toml"


def load_tickers() -> list[str]:
    """watchlist.tomlからティッカーリストを読み込む"""
    import tomllib

    with open(CONFIG_PATH, "rb") as f:
        config = tomllib.load(f)
    return config["universe"]["tickers"]


def fetch_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """yfinanceで株価OHLCVを一括取得し、整形したDataFrameを返す"""
    print(f"株価取得中... {len(tickers)}銘柄 ({start} ~ {end})")

    raw = yf.download(tickers, start=str(start), end=str(end), group_by="ticker", threads=True)

    if raw.empty:
        print("データが取得できなかった")
        return pd.DataFrame()

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
            # yfinance 1.2.x のカラム名対応（MultiIndex解除後）
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
            print(f"  スキップ: {ticker}")
            continue

    if not rows:
        return pd.DataFrame()

    result = pd.concat(rows, ignore_index=True)
    print(f"  取得完了: {len(result)}行")
    return result


def run(days: int = 30) -> None:
    """株価データを取得してParquetに保存する"""
    tickers = load_tickers()
    end = date.today()
    start = end - timedelta(days=days)

    df = fetch_prices(tickers, start, end)
    if df.empty:
        print("保存するデータなし")
        return

    prices_dir = DATA_DIR / "prices"
    append_to_monthly_parquet(df, prices_dir)
    print(f"保存完了: {prices_dir}")


if __name__ == "__main__":
    run()
