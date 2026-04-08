"""テクニカル指標算出（pandas-ta）

Parquetから株価を読み込み、テクニカル指標を算出して書き戻す。
"""

import pandas as pd
import pandas_ta as ta

from stock_report.db import DATA_DIR, query, save_parquet


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """1銘柄のOHLCVデータにテクニカル指標を追加する"""
    df = df.sort_values("date").reset_index(drop=True)

    # 移動平均線
    df["sma_25"] = ta.sma(df["close"], length=25)
    df["sma_75"] = ta.sma(df["close"], length=75)
    df["sma_200"] = ta.sma(df["close"], length=200)

    # RSI
    df["rsi_14"] = ta.rsi(df["close"], length=14)

    # MACD
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd is not None:
        df["macd"] = macd.iloc[:, 0]
        df["macd_signal"] = macd.iloc[:, 2]
        df["macd_hist"] = macd.iloc[:, 1]

    # ボリンジャーバンド
    bb = ta.bbands(df["close"], length=20, std=2)
    if bb is not None:
        df["bb_lower"] = bb.iloc[:, 0]
        df["bb_middle"] = bb.iloc[:, 1]
        df["bb_upper"] = bb.iloc[:, 2]

    # ATR
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    return df


def run() -> None:
    """全銘柄のテクニカル指標を算出し、Parquetに書き戻す"""
    print("テクニカル指標算出中...")

    prices = query("SELECT * FROM 'data/prices/*.parquet' ORDER BY ticker, date")
    if prices.empty:
        print("株価データなし")
        return

    results = []
    tickers = prices["ticker"].unique()
    for ticker in tickers:
        ticker_df = prices[prices["ticker"] == ticker].copy()
        ticker_df = compute_indicators(ticker_df)
        results.append(ticker_df)

    df = pd.concat(results, ignore_index=True)

    # 月別に分割して保存
    df["date"] = pd.to_datetime(df["date"])
    df["_month"] = df["date"].dt.to_period("M").astype(str)

    prices_dir = DATA_DIR / "prices"
    for month, group in df.groupby("_month"):
        path = prices_dir / f"{month}.parquet"
        save_parquet(group.drop(columns=["_month"]), path)

    print(f"  {len(tickers)}銘柄のテクニカル指標を算出・保存完了")


if __name__ == "__main__":
    run()
