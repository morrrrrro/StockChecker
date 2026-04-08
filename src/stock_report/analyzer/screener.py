"""3スクリーン実行 + 収束シグナル検出

Screen A: バリュー＋クオリティ（Greenblatt-Piotroski ハイブリッド簡易版）
Screen B: モメンタムブレイクアウト
Screen C: 配当バリュー
"""

from datetime import date

import duckdb
import pandas as pd

from stock_report.analyzer.scoring import compute_scores
from stock_report.db import DATA_DIR, save_parquet


def screen_a(scored: pd.DataFrame) -> pd.DataFrame:
    """Screen A: バリュー＋クオリティ（Greenblatt-Piotroski ハイブリッド）

    F-Scoreデータがある場合: 益利回り上位20% + ROC上位20% + F-Score>=7
    F-Scoreデータがない場合: 益利回り上位20% + ROE上位20%（フォールバック）
    """
    if scored.empty:
        return pd.DataFrame()

    # F-Scoreデータを読み込み
    fscore_path = DATA_DIR / "fundamentals" / "fscore.parquet"
    try:
        fscore_df = pd.read_parquet(fscore_path)
        has_fscore = True
    except FileNotFoundError:
        fscore_df = pd.DataFrame()
        has_fscore = False

    if has_fscore and not fscore_df.empty:
        # 完全版: Magic Formula + F-Score
        df = scored.merge(fscore_df[["ticker", "f_score", "earnings_yield", "roc"]], on="ticker", how="inner",
                          suffixes=("", "_fs"))
        df = df.dropna(subset=["earnings_yield_fs", "roc"])
        if df.empty:
            return _screen_a_fallback(scored)

        ey_threshold = df["earnings_yield_fs"].quantile(0.80)
        roc_threshold = df["roc"].quantile(0.80)

        mask = (
            (df["earnings_yield_fs"] >= ey_threshold)
            & (df["roc"] >= roc_threshold)
            & (df["f_score"] >= 7)
        )
        result = df[mask].copy()
        result["screen_type"] = "screen_a"
        result["detail"] = result.apply(
            lambda r: f"益利回り={r['earnings_yield_fs']:.1f}%, ROC={r['roc']:.1f}%, F-Score={int(r['f_score'])}",
            axis=1,
        )
        return result
    else:
        return _screen_a_fallback(scored)


def _screen_a_fallback(scored: pd.DataFrame) -> pd.DataFrame:
    """Screen A フォールバック: F-Scoreなしの簡易版"""
    df = scored.dropna(subset=["per", "roe"]).copy()
    if df.empty:
        return pd.DataFrame()

    earnings_yield = 1 / df["per"]
    ey_threshold = earnings_yield.quantile(0.80)
    roe_threshold = df["roe"].quantile(0.80)

    mask = (earnings_yield >= ey_threshold) & (df["roe"] >= roe_threshold)
    result = df[mask].copy()
    result["screen_type"] = "screen_a"
    result["detail"] = result.apply(
        lambda r: f"益利回り上位, ROE={r['roe']:.1f}%" if pd.notna(r["roe"]) else "益利回り上位",
        axis=1,
    )
    return result


def screen_b(scored: pd.DataFrame) -> pd.DataFrame:
    """Screen B: モメンタムブレイクアウト

    6ヶ月リターン上位20% + 200日線上 + RSI 30-70
    """
    if scored.empty:
        return pd.DataFrame()

    df = scored.dropna(subset=["return_6m", "rsi_14"]).copy()
    if df.empty:
        return pd.DataFrame()

    return_threshold = df["return_6m"].quantile(0.80)

    mask = (
        (df["return_6m"] >= return_threshold)
        & (df["above_200dma"] > 0)
        & (df["rsi_14"] >= 30)
        & (df["rsi_14"] <= 70)
    )
    result = df[mask].copy()
    result["screen_type"] = "screen_b"
    result["detail"] = result.apply(
        lambda r: f"6Mリターン={r['return_6m']:+.1f}%, RSI={r['rsi_14']:.0f}, 200日線上",
        axis=1,
    )
    return result


def screen_c(scored: pd.DataFrame) -> pd.DataFrame:
    """Screen C: 配当バリュー

    配当利回り3%以上 + PBR1.2倍以下 + 高値からの下落15%以内
    """
    if scored.empty:
        return pd.DataFrame()

    df = scored.dropna(subset=["dividend_yield", "pbr", "drawdown_from_high"]).copy()
    if df.empty:
        return pd.DataFrame()

    mask = (
        (df["dividend_yield"] >= 3.0)
        & (df["pbr"] <= 1.2)
        & (df["drawdown_from_high"] >= -15.0)
    )
    result = df[mask].copy()
    result["screen_type"] = "screen_c"
    result["detail"] = result.apply(
        lambda r: f"配当={r['dividend_yield']:.1f}%, PBR={r['pbr']:.2f}",
        axis=1,
    )
    return result


def detect_convergence(signals: pd.DataFrame) -> pd.DataFrame:
    """複数スクリーンに同時出現する銘柄（収束シグナル）を検出する"""
    if signals.empty:
        return pd.DataFrame()

    counts = signals.groupby("ticker")["screen_type"].nunique()
    convergence_tickers = counts[counts >= 2].index

    if convergence_tickers.empty:
        return pd.DataFrame()

    # 収束銘柄の最高スコアを採用
    conv = signals[signals["ticker"].isin(convergence_tickers)].copy()
    conv = conv.sort_values("composite_score", ascending=False).drop_duplicates("ticker")
    conv["screen_type"] = "convergence"

    screens = signals[signals["ticker"].isin(convergence_tickers)].groupby("ticker")["screen_type"].apply(
        lambda x: " + ".join(sorted(x.unique()))
    )
    conv = conv.merge(screens.rename("screens"), on="ticker")
    conv["detail"] = conv.apply(
        lambda r: f"収束シグナル ({r['screens']})",
        axis=1,
    )
    return conv.drop(columns=["screens"])


def run(target_date: date | None = None) -> None:
    """スクリーニングを実行し、結果をParquetに保存する"""
    if target_date is None:
        target_date = date.today()

    print("スクリーニング実行中...")

    # スコアリング
    scored = compute_scores(target_date)
    if scored.empty:
        print("スコアリング対象データなし")
        return

    print(f"  スコアリング完了: {len(scored)}銘柄")

    # 3スクリーン実行
    results = []
    for name, screen_fn in [("A: Value+Quality", screen_a), ("B: Momentum", screen_b), ("C: Dividend", screen_c)]:
        result = screen_fn(scored)
        print(f"  Screen {name}: {len(result)}銘柄")
        results.append(result)

    signals = pd.concat(results, ignore_index=True)

    # 収束シグナル検出
    convergence = detect_convergence(signals)
    if not convergence.empty:
        print(f"  収束シグナル: {len(convergence)}銘柄")
        signals = pd.concat([signals, convergence], ignore_index=True)

    if signals.empty:
        print("シグナルなし")
        return

    # 保存するカラム
    output_cols = [
        "date", "ticker", "screen_type",
        "composite_score", "value_score", "quality_score", "momentum_score", "risk_score",
        "detail",
    ]
    existing_cols = [c for c in output_cols if c in signals.columns]
    signals = signals[existing_cols]

    # 日別Parquetに保存（実データの日付を使用）
    actual_date = pd.to_datetime(scored["date"].iloc[0]).strftime("%Y-%m-%d")
    path = DATA_DIR / "signals" / f"{actual_date}.parquet"
    save_parquet(signals, path)
    print(f"  保存完了: {path} ({len(signals)}シグナル)")
    return actual_date


if __name__ == "__main__":
    run()
