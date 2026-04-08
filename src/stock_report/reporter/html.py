"""静的HTMLレポート生成（Plotly + Jinja2）"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader

from stock_report.db import DATA_DIR
from stock_report.universe import get_name_map

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates"
REPORTS_DIR = PROJECT_ROOT / "reports"

# 指標の表示名
INDICATOR_LABELS = {
    "nikkei225": "Nikkei 225",
    "topix": "TOPIX",
    "sp500": "S&P 500",
    "dow": "Dow Jones",
    "nasdaq": "NASDAQ",
    "usdjpy": "USD/JPY",
    "us10y": "US 10Y",
    "vix": "VIX",
}

# Plotly共通レイアウト
CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=10, r=10, t=30, b=10),
    font=dict(size=11),
)

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _format_value(indicator: str, value: float) -> str:
    """指標に応じた値の表示フォーマット"""
    if indicator in ("usdjpy", "eurjpy", "eurusd", "gbpjpy"):
        return f"{value:.2f}"
    if indicator in ("us10y", "us2y", "vix"):
        return f"{value:.2f}"
    return f"{value:,.0f}"


def _build_market_metrics(report_date: date) -> list[dict]:
    """市場指標メトリクスを構築する"""
    try:
        import duckdb
        df = duckdb.sql(f"""
            SELECT indicator, value, change_pct
            FROM read_parquet('data/market/*.parquet', union_by_name=True)
            WHERE date = (
                SELECT MAX(date) FROM read_parquet('data/market/*.parquet', union_by_name=True) WHERE date <= '{report_date}'
            )
        """).fetchdf()
    except Exception:
        return []

    metrics = []
    order = ["nikkei225", "sp500", "dow", "nasdaq", "usdjpy", "us10y", "vix"]
    for ind in order:
        row = df[df["indicator"] == ind]
        if row.empty:
            continue
        r = row.iloc[0]
        metrics.append({
            "label": INDICATOR_LABELS.get(ind, ind),
            "value": _format_value(ind, r["value"]),
            "change": round(r["change_pct"], 2) if pd.notna(r["change_pct"]) else 0,
        })
    return metrics


def _generate_commentary(report_date: date, market_metrics: list[dict]) -> list[str]:
    """マーケットコメンタリーを自動生成する"""
    import duckdb

    lines = []

    # 市場指標の変動から要因を分析
    metric_map = {m["label"]: m for m in market_metrics}

    # 日経225の動向
    nikkei = metric_map.get("Nikkei 225")
    sp500 = metric_map.get("S&P 500")
    usdjpy = metric_map.get("USD/JPY")
    vix = metric_map.get("VIX")

    if sp500:
        chg = sp500["change"]
        direction = "上昇" if chg >= 0 else "下落"
        lines.append(f"米国市場: S&P500は前日比{chg:+.2f}%の{direction}。")

    if usdjpy:
        chg = usdjpy["change"]
        if abs(chg) >= 0.3:
            direction = "円安" if chg > 0 else "円高"
            lines.append(f"為替: ドル円は{usdjpy['value']}円で{direction}方向（{chg:+.2f}%）。輸出関連銘柄に{'追い風' if chg > 0 else '逆風'}。")

    if vix:
        vix_val = float(vix["value"])
        if vix_val > 30:
            lines.append(f"VIXが{vix_val:.1f}と高水準。市場のリスク警戒感が強い。")
        elif vix_val > 20:
            lines.append(f"VIXは{vix_val:.1f}でやや高め。不透明感が残る。")

    # セクター動向の分析
    try:
        sector_df = duckdb.sql(f"""
            WITH latest AS (
                SELECT p.ticker, p.close, f.sector, f.market_cap
                FROM read_parquet('data/prices/*.parquet', union_by_name=True) p
                JOIN 'data/fundamentals/latest.parquet' f ON p.ticker = f.ticker
                WHERE p.date <= '{report_date}' AND f.sector IS NOT NULL
                QUALIFY ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) = 1
            ),
            prev AS (
                SELECT p.ticker, p.close as prev_close
                FROM read_parquet('data/prices/*.parquet', union_by_name=True) p
                WHERE p.date < '{report_date}'
                QUALIFY ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) = 1
            )
            SELECT l.sector,
                   ROUND(AVG((l.close - p.prev_close) / p.prev_close * 100), 2) as avg_return
            FROM latest l JOIN prev p ON l.ticker = p.ticker
            WHERE l.market_cap IS NOT NULL
            GROUP BY l.sector
            ORDER BY avg_return DESC
        """).fetchdf()

        if not sector_df.empty:
            top = sector_df.head(2)
            bottom = sector_df.tail(2)
            top_sectors = "、".join(f"{r['sector']}({r['avg_return']:+.1f}%)" for _, r in top.iterrows())
            bottom_sectors = "、".join(f"{r['sector']}({r['avg_return']:+.1f}%)" for _, r in bottom.iterrows())
            lines.append(f"セクター: {top_sectors}が強い。{bottom_sectors}が弱い。")
    except Exception:
        pass

    return lines


def _build_sector_chart(report_date: date, name_map: dict) -> str | None:
    """セクター別ヒートマップ（Treemap）を生成する"""
    try:
        import duckdb
        df = duckdb.sql(f"""
            WITH latest AS (
                SELECT p.ticker, p.close, p.date,
                       f.sector, f.market_cap
                FROM read_parquet('data/prices/*.parquet', union_by_name=True) p
                JOIN 'data/fundamentals/latest.parquet' f ON p.ticker = f.ticker
                WHERE p.date <= '{report_date}'
                QUALIFY ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) = 1
            ),
            prev AS (
                SELECT p.ticker, p.close as prev_close
                FROM read_parquet('data/prices/*.parquet', union_by_name=True) p
                JOIN latest l ON p.ticker = l.ticker AND p.date < l.date
                QUALIFY ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) = 1
            )
            SELECT l.ticker, l.sector, l.market_cap,
                   ROUND((l.close - p.prev_close) / p.prev_close * 100, 2) as daily_return
            FROM latest l
            JOIN prev p ON l.ticker = p.ticker
            WHERE l.sector IS NOT NULL AND l.market_cap IS NOT NULL
        """).fetchdf()
    except Exception:
        return None

    if df.empty:
        return None

    df["name"] = df["ticker"].map(name_map).fillna(df["ticker"])
    df["label"] = df["name"].str[:8]

    fig = px.treemap(
        df, path=["sector", "label"], values="market_cap",
        color="daily_return", color_continuous_scale="RdBu_r", color_continuous_midpoint=0,
        hover_data={"daily_return": ":.2f%"},
    )
    fig.update_layout(**CHART_LAYOUT, height=350)
    fig.update_layout(coloraxis_colorbar=dict(title="%", thickness=15, len=0.6))
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})


def _build_top_picks(signals: pd.DataFrame, scored: pd.DataFrame, name_map: dict) -> list[dict]:
    """買い推奨 Top Picks を構築する（収束シグナル優先、上位10銘柄）"""
    if signals.empty:
        return []

    # 収束シグナルを優先、なければスコア上位
    conv = signals[signals["screen_type"] == "convergence"].copy()
    if not conv.empty:
        picks_df = conv.sort_values("composite_score", ascending=False).head(10)
    else:
        picks_df = signals.sort_values("composite_score", ascending=False).drop_duplicates("ticker").head(10)

    picks = []
    for _, r in picks_df.iterrows():
        ticker = r["ticker"]
        name = name_map.get(ticker, "")
        # scored から詳細指標を取得
        scored_row = scored[scored["ticker"] == ticker]
        info = scored_row.iloc[0] if not scored_row.empty else {}

        screen_types = signals[signals["ticker"] == ticker]["screen_type"].unique()
        screens = [s for s in screen_types if s != "convergence"]

        pick = {
            "ticker": ticker,
            "name": name,
            "score": round(r.get("composite_score", 0), 1) if pd.notna(r.get("composite_score")) else "-",
            "screens": screens,
            "detail": r.get("detail", ""),
            "per": f"{info.get('per', 0):.1f}" if pd.notna(info.get("per")) else "-",
            "pbr": f"{info.get('pbr', 0):.2f}" if pd.notna(info.get("pbr")) else "-",
            "div_yield": f"{info.get('dividend_yield', 0):.1f}%" if pd.notna(info.get("dividend_yield")) else "-",
            "roe": f"{info.get('roe', 0):.1f}%" if pd.notna(info.get("roe")) else "-",
            "return_6m": f"{info.get('return_6m', 0):+.1f}%" if pd.notna(info.get("return_6m")) else "-",
            "rsi": f"{info.get('rsi_14', 0):.0f}" if pd.notna(info.get("rsi_14")) else "-",
        }
        picks.append(pick)

    return picks


def _build_signal_table(signals: pd.DataFrame, name_map: dict, screen_type: str | None = None) -> str:
    """シグナルテーブルのHTMLを生成する（ページネーション付き）"""
    if signals.empty:
        return "<p style='color: #8b8b8b;'>No signals</p>"

    df = signals.copy()
    if screen_type:
        df = df[df["screen_type"] == screen_type]

    if df.empty:
        return "<p style='color: #8b8b8b;'>No signals</p>"

    df = df.sort_values("composite_score", ascending=False)

    rows_html = []
    for _, r in df.iterrows():
        score = r.get("composite_score", 0)
        score_val = round(score, 1) if pd.notna(score) else "-"
        score_pct = min(score, 100) if pd.notna(score) else 0

        badge_class = f"badge-{r['screen_type']}"
        screen_label = {
            "screen_a": "V+Q", "screen_b": "Mom", "screen_c": "Div", "convergence": "Conv",
        }.get(r["screen_type"], r["screen_type"])

        ticker = r["ticker"]
        name = name_map.get(ticker, "")
        name_short = name[:12] if name else ""

        rows_html.append(f"""
        <tr>
          <td><strong>{ticker}</strong><br><span class="text-muted">{name_short}</span></td>
          <td><span class="badge {badge_class}">{screen_label}</span></td>
          <td>{score_val}
            <div class="score-bar"><div class="score-fill" style="width:{score_pct}%"></div></div>
          </td>
          <td>{r.get('detail', '')}</td>
        </tr>""")

    return f"""
    <table>
      <thead><tr><th>Ticker</th><th>Screen</th><th>Score</th><th>Detail</th></tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>"""


def _build_scatter_chart(scored: pd.DataFrame, name_map: dict) -> str | None:
    """バリュー vs モメンタムの散布図を生成する"""
    df = scored.dropna(subset=["value_score", "momentum_score"]).copy()
    if df.empty:
        return None

    df["name"] = df["ticker"].map(name_map).fillna(df["ticker"])
    df["label"] = df.apply(lambda r: f"{r['ticker']} {r['name'][:6]}", axis=1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["value_score"], y=df["momentum_score"],
        mode="markers",
        marker=dict(
            size=df["market_cap"].apply(lambda x: max(6, min(25, (x or 0) / 1e12 * 8 + 6)) if pd.notna(x) else 8),
            color=df["composite_score"], colorscale="Viridis", showscale=True,
            colorbar=dict(title="Score", thickness=12, len=0.6),
        ),
        text=df["label"],
        hovertemplate="<b>%{text}</b><br>Value: %{x:.0f}<br>Momentum: %{y:.0f}<extra></extra>",
    ))
    fig.add_hline(y=50, line_dash="dot", line_color="#444", line_width=1)
    fig.add_vline(x=50, line_dash="dot", line_color="#444", line_width=1)

    fig.update_layout(
        **CHART_LAYOUT, height=400,
        xaxis=dict(title="Value Score", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
        yaxis=dict(title="Momentum Score", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def generate_report(report_date: date | None = None) -> Path:
    """静的HTMLレポートを生成する"""
    if report_date is None:
        report_date = date.today()

    print(f"HTMLレポート生成中... ({report_date})")

    # 銘柄名マッピング
    name_map = get_name_map()

    market_metrics = _build_market_metrics(report_date)

    # マーケットコメンタリー生成
    highlights = _generate_commentary(report_date, market_metrics)

    # シグナル
    signal_path = DATA_DIR / "signals" / f"{report_date}.parquet"
    try:
        signals = pd.read_parquet(signal_path)
    except FileNotFoundError:
        signals = pd.DataFrame()

    # スコアリング結果
    from stock_report.analyzer.scoring import compute_scores
    scored = compute_scores(report_date)

    # Top Picks（買い推奨）
    top_picks = _build_top_picks(signals, scored, name_map)

    # ライフサイクル
    lifecycle_path = DATA_DIR / "signals" / "lifecycle.parquet"
    try:
        lifecycle = pd.read_parquet(lifecycle_path)
        lifecycle["name"] = lifecycle["ticker"].map(name_map).fillna("")
        lifecycle_data = lifecycle.sort_values("days_active", ascending=False).to_dict("records")
    except FileNotFoundError:
        lifecycle_data = []

    # ウォッチリスト・テーゼチェック
    from stock_report.watchlist import get_holdings, get_watching, check_thesis
    thesis_alerts = check_thesis(report_date)
    holdings = get_holdings()
    watching = get_watching()

    # 保有銘柄に名前を付与
    for h in holdings:
        h["name"] = name_map.get(h["ticker"], "")
    for w in watching:
        w["name"] = name_map.get(w["ticker"], "")
    for a in thesis_alerts:
        a["name"] = name_map.get(a["ticker"], "")

    # チャート生成
    sector_chart = _build_sector_chart(report_date, name_map)
    scatter_chart = _build_scatter_chart(scored, name_map) if not scored.empty else None

    convergence_count = len(signals[signals["screen_type"] == "convergence"]) if not signals.empty else 0

    # テンプレートレンダリング
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html")

    html = template.render(
        report_date=str(report_date),
        weekday=WEEKDAY_JP[report_date.weekday()],
        market_metrics=market_metrics,
        highlights=highlights,
        top_picks=top_picks,
        thesis_alerts=thesis_alerts,
        holdings=holdings,
        watching=watching,
        sector_chart=sector_chart,
        signals=signals.to_dict("records") if not signals.empty else [],
        signal_table_html=_build_signal_table(signals, name_map),
        signal_table_a_html=_build_signal_table(signals, name_map, "screen_a"),
        signal_table_b_html=_build_signal_table(signals, name_map, "screen_b"),
        signal_table_c_html=_build_signal_table(signals, name_map, "screen_c"),
        signal_table_conv_html=_build_signal_table(signals, name_map, "convergence"),
        convergence_count=convergence_count,
        scatter_chart=scatter_chart,
        lifecycle_data=lifecycle_data,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORTS_DIR / f"{report_date}.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"  レポート保存: {output_path}")

    _update_index(report_date)
    return output_path


def _update_index(latest_date: date) -> None:
    """index.htmlを最新レポートへのリダイレクト + アーカイブ一覧で更新する"""
    report_files = sorted(REPORTS_DIR.glob("20*.html"), reverse=True)
    archive_links = "\n".join(
        f'    <li><a href="{f.name}">{f.stem}</a></li>'
        for f in report_files[:30]
    )
    index_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url={latest_date}.html">
<title>Stock Report</title>
<style>
  body {{ font-family: sans-serif; background: #0E1117; color: #e0e0e0; padding: 20px; }}
  a {{ color: #6C9BCF; }}
  li {{ margin: 4px 0; }}
</style>
</head>
<body>
  <p>Redirecting to <a href="{latest_date}.html">latest report</a>...</p>
  <h3>Archive</h3>
  <ul>
{archive_links}
  </ul>
</body>
</html>"""
    (REPORTS_DIR / "index.html").write_text(index_html, encoding="utf-8")


if __name__ == "__main__":
    generate_report()
