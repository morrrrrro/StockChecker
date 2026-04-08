"""マルチファクタースコアリング

パーセンタイルランクで各ファクターを正規化し、加重平均で総合スコアを算出する。

Composite Score = 0.35×Value + 0.30×Quality + 0.25×Momentum + 0.10×Risk
"""

from datetime import date, timedelta

import duckdb
import pandas as pd

from stock_report.db import DATA_DIR


# スコアリングの重み
WEIGHTS = {
    "value": 0.35,
    "quality": 0.30,
    "momentum": 0.25,
    "risk": 0.10,
}


def compute_scores(target_date: date | None = None) -> pd.DataFrame:
    """全銘柄のマルチファクタースコアを算出する

    target_dateの直近営業日データを使用する。
    """
    if target_date is None:
        target_date = date.today()

    # 直近の株価データ取得（target_date以前の最新日）
    latest_prices = duckdb.sql(f"""
        SELECT *
        FROM 'data/prices/*.parquet'
        WHERE date <= '{target_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
    """).fetchdf()

    if latest_prices.empty:
        return pd.DataFrame()

    # 6ヶ月前の株価（モメンタム算出用）
    six_months_ago = target_date - timedelta(days=180)
    prices_6m = duckdb.sql(f"""
        SELECT ticker, close as close_6m
        FROM 'data/prices/*.parquet'
        WHERE date <= '{six_months_ago}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
    """).fetchdf()

    # ファンダメンタルデータ読み込み
    try:
        fundamentals = pd.read_parquet(DATA_DIR / "fundamentals" / "latest.parquet")
    except FileNotFoundError:
        fundamentals = pd.DataFrame(columns=["ticker", "per", "pbr", "dividend_yield", "roe"])

    # データ結合
    df = latest_prices.merge(prices_6m, on="ticker", how="left")
    df = df.merge(fundamentals, on="ticker", how="left")

    # 派生指標算出
    df["return_6m"] = (df["close"] - df["close_6m"]) / df["close_6m"] * 100
    df["above_200dma"] = (df["close"] > df["sma_200"]).astype(float) * 100
    df["earnings_yield"] = df["per"].apply(lambda x: 1 / x * 100 if x and x > 0 else None)
    df["pbr_inv"] = df["pbr"].apply(lambda x: 1 / x if x and x > 0 else None)

    # ボラティリティ（ATRベース、低い方が良い）
    df["low_volatility"] = df["atr_14"].apply(lambda x: -x if x else None)

    # 52週高値からのドローダウン（小さい方が良い = リスク低い）
    high_52w = duckdb.sql(f"""
        SELECT ticker, MAX(high) as high_52w
        FROM 'data/prices/*.parquet'
        WHERE date >= '{target_date - timedelta(days=365)}'
        GROUP BY ticker
    """).fetchdf()
    df = df.merge(high_52w, on="ticker", how="left")
    df["drawdown_from_high"] = (df["close"] - df["high_52w"]) / df["high_52w"] * 100
    df["low_drawdown"] = -df["drawdown_from_high"].abs()

    # 出来高（流動性、高い方が良い）
    avg_volume = duckdb.sql(f"""
        SELECT ticker, AVG(volume) as avg_volume_20d
        FROM 'data/prices/*.parquet'
        WHERE date >= '{target_date - timedelta(days=30)}'
        GROUP BY ticker
    """).fetchdf()
    df = df.merge(avg_volume, on="ticker", how="left")

    # パーセンタイルランク算出
    def pct_rank(series: pd.Series) -> pd.Series:
        return series.rank(pct=True, na_option="bottom") * 100

    # Value Score = avg(益利回り, 1/PBR, 配当利回り)
    df["pct_earnings_yield"] = pct_rank(df["earnings_yield"])
    df["pct_pbr_inv"] = pct_rank(df["pbr_inv"])
    df["pct_dividend_yield"] = pct_rank(df["dividend_yield"])
    df["value_score"] = df[["pct_earnings_yield", "pct_pbr_inv", "pct_dividend_yield"]].mean(axis=1)

    # Quality Score = avg(ROE) ※Phase 6でFCFマージン, F-Scoreを追加
    df["pct_roe"] = pct_rank(df["roe"])
    df["quality_score"] = df["pct_roe"]

    # Momentum Score = 0.5×6M_return + 0.3×RS_rank + 0.2×above_200dma
    df["pct_return_6m"] = pct_rank(df["return_6m"])
    df["momentum_score"] = (
        0.5 * df["pct_return_6m"]
        + 0.3 * pct_rank(df["return_6m"])  # RS rankは6Mリターンの順位そのもの
        + 0.2 * df["above_200dma"]
    )

    # Risk Score = avg(低ボラティリティ, 低ドローダウン, 流動性)
    df["pct_low_vol"] = pct_rank(df["low_volatility"])
    df["pct_low_dd"] = pct_rank(df["low_drawdown"])
    df["pct_liquidity"] = pct_rank(df["avg_volume_20d"])
    df["risk_score"] = df[["pct_low_vol", "pct_low_dd", "pct_liquidity"]].mean(axis=1)

    # Composite Score
    df["composite_score"] = (
        WEIGHTS["value"] * df["value_score"]
        + WEIGHTS["quality"] * df["quality_score"]
        + WEIGHTS["momentum"] * df["momentum_score"]
        + WEIGHTS["risk"] * df["risk_score"]
    )

    # 整理して返す
    output_cols = [
        "date", "ticker", "close",
        "composite_score", "value_score", "quality_score", "momentum_score", "risk_score",
        "per", "pbr", "dividend_yield", "roe",
        "return_6m", "rsi_14", "sma_200", "above_200dma",
        "atr_14", "drawdown_from_high", "avg_volume_20d",
        "sector", "market_cap",
    ]
    existing_cols = [c for c in output_cols if c in df.columns]
    return df[existing_cols].sort_values("composite_score", ascending=False).reset_index(drop=True)
