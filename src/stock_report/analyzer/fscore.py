"""Piotroski F-Score + Magic Formula 算出

yfinanceの財務諸表データ（.financials, .balance_sheet, .cashflow）を使って
F-ScoreとMagic Formula指標を計算する。
"""

import pandas as pd
import yfinance as yf

from stock_report.db import DATA_DIR, save_parquet


def _safe_get(df: pd.DataFrame, key: str, col: int = 0) -> float | None:
    """財務諸表から安全に値を取得する"""
    if df is None or df.empty or key not in df.index:
        return None
    val = df.iloc[:, col] if col < len(df.columns) else None
    if val is None:
        return None
    v = df.loc[key].iloc[col]
    return float(v) if pd.notna(v) else None


def compute_fscore(ticker: str) -> dict:
    """Piotroski F-Score（9項目）を算出する

    Returns: {"ticker": str, "f_score": int, ...各項目}
    """
    t = yf.Ticker(ticker)

    try:
        fs = t.financials
        bs = t.balance_sheet
        cf = t.cashflow
    except Exception:
        return {"ticker": ticker, "f_score": None}

    if fs is None or fs.empty or bs is None or bs.empty:
        return {"ticker": ticker, "f_score": None}

    # 当期・前期のデータ取得（カラム0=最新、カラム1=前年）
    has_prior = len(fs.columns) >= 2 and len(bs.columns) >= 2

    # 当期の値
    net_income = _safe_get(fs, "Net Income")
    total_assets = _safe_get(bs, "Total Assets")
    total_assets_prev = _safe_get(bs, "Total Assets", 1) if has_prior else None
    operating_cf = _safe_get(cf, "Operating Cash Flow") if cf is not None else None
    long_term_debt = _safe_get(bs, "Long Term Debt")
    long_term_debt_prev = _safe_get(bs, "Long Term Debt", 1) if has_prior else None
    current_assets = _safe_get(bs, "Current Assets")
    current_liabilities = _safe_get(bs, "Current Liabilities")
    current_assets_prev = _safe_get(bs, "Current Assets", 1) if has_prior else None
    current_liabilities_prev = _safe_get(bs, "Current Liabilities", 1) if has_prior else None
    gross_profit = _safe_get(fs, "Gross Profit")
    revenue = _safe_get(fs, "Total Revenue")
    gross_profit_prev = _safe_get(fs, "Gross Profit", 1) if has_prior else None
    revenue_prev = _safe_get(fs, "Total Revenue", 1) if has_prior else None
    shares = _safe_get(bs, "Share Issued")
    shares_prev = _safe_get(bs, "Share Issued", 1) if has_prior else None
    net_income_prev = _safe_get(fs, "Net Income", 1) if has_prior else None

    # F-Score計算（各項目 0 or 1）
    score = 0
    details = {}

    # 収益性（4点）
    # 1. ROA > 0
    roa = net_income / total_assets if net_income and total_assets else None
    f_roa = 1 if roa and roa > 0 else 0
    details["f_roa"] = f_roa
    score += f_roa

    # 2. 営業CF > 0
    f_cfo = 1 if operating_cf and operating_cf > 0 else 0
    details["f_cfo"] = f_cfo
    score += f_cfo

    # 3. ROA改善（前年比）
    roa_prev = net_income_prev / total_assets_prev if net_income_prev and total_assets_prev else None
    f_droa = 1 if roa and roa_prev and roa > roa_prev else 0
    details["f_droa"] = f_droa
    score += f_droa

    # 4. アクルーアル品質（営業CF/総資産 > ROA）
    cfo_ratio = operating_cf / total_assets if operating_cf and total_assets else None
    f_accrual = 1 if cfo_ratio and roa and cfo_ratio > roa else 0
    details["f_accrual"] = f_accrual
    score += f_accrual

    # レバレッジ・流動性（3点）
    # 5. 長期負債比率の改善
    debt_ratio = long_term_debt / total_assets if long_term_debt and total_assets else 0
    debt_ratio_prev = long_term_debt_prev / total_assets_prev if long_term_debt_prev and total_assets_prev else 0
    f_dlever = 1 if debt_ratio <= debt_ratio_prev else 0
    details["f_dlever"] = f_dlever
    score += f_dlever

    # 6. 流動比率の改善
    cr = current_assets / current_liabilities if current_assets and current_liabilities else None
    cr_prev = current_assets_prev / current_liabilities_prev if current_assets_prev and current_liabilities_prev else None
    f_dliquid = 1 if cr and cr_prev and cr > cr_prev else 0
    details["f_dliquid"] = f_dliquid
    score += f_dliquid

    # 7. 新株発行なし
    f_equity = 1 if shares and shares_prev and shares <= shares_prev else (1 if not shares_prev else 0)
    details["f_equity"] = f_equity
    score += f_equity

    # 営業効率（2点）
    # 8. 粗利率の改善
    gm = gross_profit / revenue if gross_profit and revenue else None
    gm_prev = gross_profit_prev / revenue_prev if gross_profit_prev and revenue_prev else None
    f_dmargin = 1 if gm and gm_prev and gm > gm_prev else 0
    details["f_dmargin"] = f_dmargin
    score += f_dmargin

    # 9. 資産回転率の改善
    at = revenue / total_assets if revenue and total_assets else None
    at_prev = revenue_prev / total_assets_prev if revenue_prev and total_assets_prev else None
    f_dturn = 1 if at and at_prev and at > at_prev else 0
    details["f_dturn"] = f_dturn
    score += f_dturn

    # Magic Formula指標
    ebit = _safe_get(fs, "EBIT")
    try:
        market_cap = t.info.get("marketCap")
    except Exception:
        market_cap = None
    total_debt = _safe_get(bs, "Total Debt")
    cash = _safe_get(bs, "Cash And Cash Equivalents")

    ev = None
    if market_cap:
        ev = market_cap + (total_debt or 0) - (cash or 0)

    earnings_yield = (ebit / ev * 100) if ebit and ev and ev > 0 else None

    working_capital = (current_assets or 0) - (current_liabilities or 0)
    net_fixed_assets = (total_assets or 0) - (current_assets or 0)
    invested_capital = working_capital + net_fixed_assets
    roc = (ebit / invested_capital * 100) if ebit and invested_capital and invested_capital > 0 else None

    return {
        "ticker": ticker,
        "f_score": score,
        "roa": round(roa * 100, 2) if roa else None,
        "operating_cf": operating_cf,
        "net_income": net_income,
        "total_assets": total_assets,
        "revenue": revenue,
        "gross_margin": round(gm * 100, 2) if gm else None,
        "current_ratio": round(cr, 2) if cr else None,
        "ebit": ebit,
        "earnings_yield": round(earnings_yield, 2) if earnings_yield else None,
        "roc": round(roc, 2) if roc else None,
        **details,
    }


def run(tickers: list[str] | None = None, max_tickers: int = 500) -> None:
    """F-Score + Magic Formula指標を算出してParquetに保存する

    全銘柄は時間がかかるため、max_tickersで上限を指定可能。
    """
    if tickers is None:
        # ファンダメンタルデータがある銘柄を優先
        try:
            fund = pd.read_parquet(DATA_DIR / "fundamentals" / "latest.parquet")
            tickers = fund["ticker"].tolist()[:max_tickers]
        except FileNotFoundError:
            from stock_report.universe import get_tse_stocks
            tickers = get_tse_stocks()[:max_tickers]

    print(f"F-Score算出中... {len(tickers)}銘柄")

    results = []
    failed = 0
    for i, ticker in enumerate(tickers):
        try:
            result = compute_fscore(ticker)
            if result["f_score"] is not None:
                results.append(result)
        except Exception:
            failed += 1

        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(tickers)} 完了 (成功: {len(results)}, 失敗: {failed})")

    if not results:
        print("算出できたデータなし")
        return

    df = pd.DataFrame(results)
    path = DATA_DIR / "fundamentals" / "fscore.parquet"
    save_parquet(df, path)
    print(f"  保存完了: {path} ({len(df)}銘柄)")

    # 統計表示
    print(f"\n  F-Score分布:")
    print(f"  {df['f_score'].value_counts().sort_index().to_string()}")
    print(f"  平均: {df['f_score'].mean():.1f}")


if __name__ == "__main__":
    import sys
    max_t = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    run(max_tickers=max_t)
