"""ファンダメンタルデータ取得（yfinance .info ベースの簡易版）

Phase 6でEDINET連携を追加し、F-Score・Magic Formula指標の完全版に拡張する。
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR, save_parquet
from stock_report.fetcher.price import load_tickers

# yfinance .infoから取得する項目
INFO_FIELDS = {
    "trailingPE": "per",
    "priceToBook": "pbr",
    "dividendYield": "dividend_yield",
    "returnOnEquity": "roe",
    "marketCap": "market_cap",
    "sector": "sector",
    "industry": "industry",
}


def fetch_fundamentals(tickers: list[str]) -> pd.DataFrame:
    """yfinance .infoからファンダメンタルデータを取得する"""
    print(f"ファンダメンタルデータ取得中... {len(tickers)}銘柄")

    rows = []
    for i, ticker in enumerate(tickers):
        try:
            info = yf.Ticker(ticker).info
            row = {"ticker": ticker}
            for yf_key, col_name in INFO_FIELDS.items():
                row[col_name] = info.get(yf_key)

            # dividend_yieldはyfinanceが日本株で既に%値（2.92 = 2.92%）を返す
            # ROEは小数（0.10 = 10%）なので%に変換
            if row["roe"] is not None:
                row["roe"] = row["roe"] * 100

            rows.append(row)
            if (i + 1) % 10 == 0:
                print(f"  {i + 1}/{len(tickers)} 完了")
        except Exception as e:
            print(f"  スキップ: {ticker} ({e})")
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    print(f"  取得完了: {len(df)}銘柄")
    return df


def run() -> None:
    """ファンダメンタルデータを取得してParquetに保存する"""
    tickers = load_tickers()
    df = fetch_fundamentals(tickers)

    if df.empty:
        print("保存するデータなし")
        return

    path = DATA_DIR / "fundamentals" / "latest.parquet"
    save_parquet(df, path)
    print(f"保存完了: {path}")


if __name__ == "__main__":
    run()
