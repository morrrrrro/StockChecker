"""ファンダメンタルデータ取得（yfinance .info ベースの簡易版）

全銘柄の取得は数時間かかるため、週次実行 or 手動実行を想定。
既存データがあれば差分更新（新規銘柄のみ追加）も可能。

Phase 6でEDINET連携を追加し、F-Score・Magic Formula指標の完全版に拡張する。
"""

import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR, save_parquet
from stock_report.universe import get_all_tickers

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

FUNDAMENTALS_PATH = DATA_DIR / "fundamentals" / "latest.parquet"


def fetch_fundamentals(tickers: list[str], resume_from: int = 0) -> pd.DataFrame:
    """yfinance .infoからファンダメンタルデータを取得する

    大量銘柄対応: 進捗表示 + エラー時もスキップして続行。
    resume_from: 途中再開用のインデックス。
    """
    total = len(tickers)
    print(f"ファンダメンタルデータ取得中... {total}銘柄 (開始: {resume_from})")

    rows = []
    failed = 0
    for i in range(resume_from, total):
        ticker = tickers[i]
        try:
            info = yf.Ticker(ticker).info
            row = {"ticker": ticker}
            for yf_key, col_name in INFO_FIELDS.items():
                row[col_name] = info.get(yf_key)

            # ROEは小数（0.10 = 10%）なので%に変換
            if row["roe"] is not None:
                row["roe"] = row["roe"] * 100

            rows.append(row)
        except Exception:
            failed += 1
            continue

        # 進捗表示（100銘柄ごと）
        done = i - resume_from + 1
        if done % 100 == 0:
            print(f"  {done}/{total - resume_from} 完了 (失敗: {failed})")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    print(f"  取得完了: {len(df)}銘柄 (失敗: {failed})")
    return df


def run(category: str | None = None, incremental: bool = False) -> None:
    """ファンダメンタルデータを取得してParquetに保存する

    category: "tse", "us", "etf" または None（全て）
    incremental: Trueの場合、既存データにない銘柄のみ取得
    """
    all_tickers = get_all_tickers()

    if category:
        tickers = all_tickers.get(category, [])
    else:
        tickers = []
        for lst in all_tickers.values():
            tickers.extend(lst)

    if not tickers:
        print("対象銘柄なし")
        return

    # 差分更新: 既存データにある銘柄をスキップ
    if incremental and FUNDAMENTALS_PATH.exists():
        existing = pd.read_parquet(FUNDAMENTALS_PATH)
        existing_tickers = set(existing["ticker"])
        new_tickers = [t for t in tickers if t not in existing_tickers]
        print(f"差分更新: {len(new_tickers)}銘柄が新規 (既存: {len(existing_tickers)})")

        if not new_tickers:
            print("新規銘柄なし")
            return

        new_df = fetch_fundamentals(new_tickers)
        if new_df.empty:
            return

        # 既存データとマージ
        df = pd.concat([existing, new_df], ignore_index=True)
        df = df.drop_duplicates(subset=["ticker"], keep="last")
    else:
        df = fetch_fundamentals(tickers)

    if df.empty:
        print("保存するデータなし")
        return

    save_parquet(df, FUNDAMENTALS_PATH)
    print(f"保存完了: {FUNDAMENTALS_PATH} ({len(df)}銘柄)")


if __name__ == "__main__":
    import sys
    # 引数: python -m stock_report.fetcher.fundamental [category] [--incremental]
    cat = None
    incr = False
    for arg in sys.argv[1:]:
        if arg == "--incremental":
            incr = True
        else:
            cat = arg
    run(category=cat, incremental=incr)
