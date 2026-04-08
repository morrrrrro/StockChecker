"""市場指標データ取得（指数・為替・債券・商品・暗号資産）"""

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR, append_to_monthly_parquet
from stock_report.universe import get_market_indicators


def fetch_market_indicators(start: date, end: date) -> pd.DataFrame:
    """各市場指標のデータを取得し、縦持ちDataFrameで返す"""
    indicators = get_market_indicators()
    print(f"市場指標取得中... {len(indicators)}指標 ({start} ~ {end})")

    rows = []
    for name, ticker in indicators.items():
        try:
            data = yf.download(ticker, start=str(start), end=str(end), progress=False)
            if data.empty:
                print(f"  スキップ: {name} ({ticker})")
                continue

            df = data.reset_index()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            # 終値と前日比を算出
            df = df.rename(columns={"Date": "date", "Close": "value"})
            df["change_pct"] = df["value"].pct_change() * 100
            df["indicator"] = name
            df = df[["date", "indicator", "value", "change_pct"]]
            df = df.dropna(subset=["value"])
            rows.append(df)
            print(f"  {name}: {len(df)}日分")
        except Exception as e:
            print(f"  エラー: {name} ({ticker}): {e}")
            continue

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows, ignore_index=True)


def run(days: int = 30) -> None:
    """市場指標データを取得してParquetに保存する"""
    end = date.today()
    start = end - timedelta(days=days)

    df = fetch_market_indicators(start, end)
    if df.empty:
        print("保存するデータなし")
        return

    market_dir = DATA_DIR / "market"
    append_to_monthly_parquet(df, market_dir)
    print(f"保存完了: {market_dir}")


if __name__ == "__main__":
    run()
