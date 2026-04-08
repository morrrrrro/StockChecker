"""ウォッチリスト管理 + テーゼチェック + 決算カレンダー"""

import tomllib
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "watchlist.toml"


def load_watchlist() -> dict:
    """watchlist.tomlを読み込む"""
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def get_holdings() -> list[dict]:
    """保有銘柄リストを返す"""
    config = load_watchlist()
    return config.get("watchlist", {}).get("holdings", [])


def get_watching() -> list[dict]:
    """注目銘柄リストを返す"""
    config = load_watchlist()
    return config.get("watchlist", {}).get("watching", [])


def get_all_watchlist_tickers() -> list[str]:
    """ウォッチリスト全銘柄のティッカーを返す"""
    tickers = []
    for h in get_holdings():
        tickers.append(h["ticker"])
    for w in get_watching():
        tickers.append(w["ticker"])
    return tickers


def check_thesis(report_date: date | None = None) -> list[dict]:
    """保有銘柄のテーゼチェック — 投資判断を変えるべき変化を検出する

    検出条件:
    - 株価が購入価格から20%以上下落
    - RSIが70超（過熱圏突入）or 30未満（売られすぎ）
    - 200日線を下回った
    - F-Scoreが4以下に悪化
    """
    if report_date is None:
        report_date = date.today()

    holdings = get_holdings()
    if not holdings:
        return []

    alerts = []
    for h in holdings:
        ticker = h["ticker"]
        buy_price = h.get("buy_price")
        thesis = h.get("thesis", "")

        # 最新の株価データを取得
        try:
            price_data = duckdb.sql(f"""
                SELECT close, rsi_14, sma_200
                FROM read_parquet('data/prices/*.parquet', union_by_name=True)
                WHERE ticker = '{ticker}' AND date <= '{report_date}'
                ORDER BY date DESC LIMIT 1
            """).fetchdf()
        except Exception:
            continue

        if price_data.empty:
            continue

        row = price_data.iloc[0]
        close = row["close"]
        rsi = row.get("rsi_14")
        sma200 = row.get("sma_200")

        reasons = []

        # 購入価格からの下落チェック
        if buy_price and close < buy_price * 0.80:
            loss_pct = (close - buy_price) / buy_price * 100
            reasons.append(f"購入価格から{loss_pct:.1f}%下落（購入: {buy_price:,.0f} → 現在: {close:,.0f}）")

        # RSI過熱/売られすぎ
        if pd.notna(rsi):
            if rsi > 70:
                reasons.append(f"RSI={rsi:.0f} — 過熱圏、利確検討")
            elif rsi < 30:
                reasons.append(f"RSI={rsi:.0f} — 売られすぎ、買い増し検討 or テーゼ再確認")

        # 200日線割れ
        if pd.notna(sma200) and close < sma200:
            reasons.append(f"200日線割れ（SMA200={sma200:,.0f}、現在={close:,.0f}）")

        # F-Score悪化
        try:
            fscore_df = pd.read_parquet(DATA_DIR / "fundamentals" / "fscore.parquet")
            fs_row = fscore_df[fscore_df["ticker"] == ticker]
            if not fs_row.empty:
                f_score = fs_row.iloc[0]["f_score"]
                if pd.notna(f_score) and f_score <= 4:
                    reasons.append(f"F-Score={int(f_score)} — 財務健全性に懸念")
        except FileNotFoundError:
            pass

        if reasons:
            alerts.append({
                "ticker": ticker,
                "thesis": thesis,
                "close": close,
                "buy_price": buy_price,
                "pnl_pct": round((close - buy_price) / buy_price * 100, 1) if buy_price else None,
                "reasons": reasons,
            })

    return alerts


def get_earnings_calendar(tickers: list[str] | None = None) -> list[dict]:
    """決算発表カレンダーを取得する（yfinance経由）"""
    if tickers is None:
        tickers = get_all_watchlist_tickers()

    if not tickers:
        return []

    events = []
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None or (isinstance(cal, pd.DataFrame) and cal.empty):
                continue

            # calはdict形式の場合がある
            if isinstance(cal, dict):
                earnings_date = cal.get("Earnings Date")
                if earnings_date:
                    if isinstance(earnings_date, list):
                        for d in earnings_date:
                            events.append({"ticker": ticker, "event": "決算発表", "date": str(d)[:10]})
                    else:
                        events.append({"ticker": ticker, "event": "決算発表", "date": str(earnings_date)[:10]})

                ex_div = cal.get("Ex-Dividend Date")
                if ex_div:
                    events.append({"ticker": ticker, "event": "配当権利落ち日", "date": str(ex_div)[:10]})
            elif isinstance(cal, pd.DataFrame):
                for col in cal.columns:
                    if "Earnings" in str(col):
                        val = cal[col].iloc[0] if not cal[col].empty else None
                        if val:
                            events.append({"ticker": ticker, "event": "決算発表", "date": str(val)[:10]})
        except Exception:
            continue

    # 日付順にソート
    events.sort(key=lambda x: x.get("date", "9999"))
    return events
