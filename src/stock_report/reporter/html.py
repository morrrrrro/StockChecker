"""静的HTMLレポート生成（Plotly + Jinja2）"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader

from stock_report.db import DATA_DIR

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
    if indicator in ("usdjpy",):
        return f"{value:.2f}"
    if indicator in ("us10y", "vix"):
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
    # 表示順序
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


def _build_sector_chart(report_date: date) -> str | None:
    """セクター別ヒートマップ（Treemap）を生成する"""
    try:
        import duckdb
        # 直近日の株価変動率をセクター別に集計
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

    fig = px.treemap(
        df,
        path=["sector", "ticker"],
        values="market_cap",
        color="daily_return",
        color_continuous_scale="RdBu_r",
        color_continuous_midpoint=0,
        hover_data={"daily_return": ":.2f%"},
    )
    fig.update_layout(**CHART_LAYOUT, height=350)
    fig.update_layout(coloraxis_colorbar=dict(title="%", thickness=15, len=0.6))
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})


def _build_signal_table(signals: pd.DataFrame, screen_type: str | None = None) -> str:
    """シグナルテーブルのHTMLを生成する"""
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
            "screen_a": "V+Q",
            "screen_b": "Mom",
            "screen_c": "Div",
            "convergence": "Conv",
        }.get(r["screen_type"], r["screen_type"])

        rows_html.append(f"""
        <tr>
          <td><strong>{r['ticker']}</strong></td>
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


def _build_scatter_chart(scored: pd.DataFrame) -> str | None:
    """バリュー vs モメンタムの散布図を生成する"""
    df = scored.dropna(subset=["value_score", "momentum_score"]).copy()
    if df.empty:
        return None

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["value_score"],
        y=df["momentum_score"],
        mode="markers+text",
        text=df["ticker"],
        textposition="top center",
        textfont=dict(size=9, color="#8b8b8b"),
        marker=dict(
            size=df["market_cap"].apply(lambda x: max(8, min(30, (x or 0) / 1e12 * 10 + 8)) if pd.notna(x) else 10),
            color=df["composite_score"],
            colorscale="Viridis",
            showscale=True,
            colorbar=dict(title="Score", thickness=12, len=0.6),
        ),
        hovertemplate="<b>%{text}</b><br>Value: %{x:.0f}<br>Momentum: %{y:.0f}<extra></extra>",
    ))

    # 4象限の線
    fig.add_hline(y=50, line_dash="dot", line_color="#444", line_width=1)
    fig.add_vline(x=50, line_dash="dot", line_color="#444", line_width=1)

    fig.update_layout(
        **CHART_LAYOUT,
        height=400,
        xaxis=dict(title="Value Score", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
        yaxis=dict(title="Momentum Score", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def generate_report(report_date: date | None = None) -> Path:
    """静的HTMLレポートを生成する"""
    if report_date is None:
        report_date = date.today()

    print(f"HTMLレポート生成中... ({report_date})")

    # データ読み込み
    market_metrics = _build_market_metrics(report_date)

    # シグナル
    signal_path = DATA_DIR / "signals" / f"{report_date}.parquet"
    try:
        signals = pd.read_parquet(signal_path)
    except FileNotFoundError:
        signals = pd.DataFrame()

    # スコアリング結果（散布図用）
    from stock_report.analyzer.scoring import compute_scores
    scored = compute_scores(report_date)

    # ライフサイクル
    lifecycle_path = DATA_DIR / "signals" / "lifecycle.parquet"
    try:
        lifecycle = pd.read_parquet(lifecycle_path)
        lifecycle_data = lifecycle.sort_values("days_active", ascending=False).to_dict("records")
    except FileNotFoundError:
        lifecycle_data = []

    # チャート生成
    sector_chart = _build_sector_chart(report_date)
    scatter_chart = _build_scatter_chart(scored) if not scored.empty else None

    # テンプレートレンダリング
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html")

    convergence_count = len(signals[signals["screen_type"] == "convergence"]) if not signals.empty else 0

    html = template.render(
        report_date=str(report_date),
        weekday=WEEKDAY_JP[report_date.weekday()],
        market_metrics=market_metrics,
        highlights=[],  # Phase 7で「今日のポイント」を自動生成する
        sector_chart=sector_chart,
        signals=signals.to_dict("records") if not signals.empty else [],
        signal_table_html=_build_signal_table(signals),
        signal_table_a_html=_build_signal_table(signals, "screen_a"),
        signal_table_b_html=_build_signal_table(signals, "screen_b"),
        signal_table_c_html=_build_signal_table(signals, "screen_c"),
        signal_table_conv_html=_build_signal_table(signals, "convergence"),
        convergence_count=convergence_count,
        scatter_chart=scatter_chart,
        lifecycle_data=lifecycle_data,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    # 保存
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORTS_DIR / f"{report_date}.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"  レポート保存: {output_path}")

    # index.html を更新
    _update_index(report_date)

    return output_path


def _update_index(latest_date: date) -> None:
    """index.htmlを最新レポートへのリダイレクト + アーカイブ一覧で更新する"""
    # 既存レポートのリスト
    report_files = sorted(REPORTS_DIR.glob("20*.html"), reverse=True)
    archive_links = "\n".join(
        f'    <li><a href="{f.name}">{f.stem}</a></li>'
        for f in report_files[:30]  # 直近30件
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
