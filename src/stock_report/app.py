"""Streamlit ダッシュボード（ローカル深掘り用）

起動: uv run streamlit run src/stock_report/app.py
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from stock_report.db import DATA_DIR
from stock_report.universe import get_name_map

# Plotly共通レイアウト
CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, t=30, b=0),
    xaxis=dict(showgrid=False),
    yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
)
CHART_CONFIG = dict(displayModeBar=False)


# --- データ読み込み（キャッシュ付き） ---

@st.cache_data(ttl=3600)
def load_name_map() -> dict[str, str]:
    return get_name_map()


@st.cache_data(ttl=3600)
def load_market_data() -> pd.DataFrame:
    try:
        return duckdb.sql("""
            SELECT * FROM read_parquet('data/market/*.parquet', union_by_name=True)
            ORDER BY date DESC
        """).fetchdf()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_signals(report_date: str) -> pd.DataFrame:
    path = DATA_DIR / "signals" / f"{report_date}.parquet"
    try:
        return pd.read_parquet(path)
    except FileNotFoundError:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_scored(report_date: str) -> pd.DataFrame:
    from stock_report.analyzer.scoring import compute_scores
    return compute_scores(date.fromisoformat(report_date))


@st.cache_data(ttl=3600)
def load_prices(ticker: str) -> pd.DataFrame:
    try:
        return duckdb.sql(f"""
            SELECT * FROM read_parquet('data/prices/*.parquet', union_by_name=True)
            WHERE ticker = '{ticker}'
            ORDER BY date
        """).fetchdf()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_fundamentals() -> pd.DataFrame:
    try:
        return pd.read_parquet(DATA_DIR / "fundamentals" / "latest.parquet")
    except FileNotFoundError:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_available_dates() -> list[str]:
    """シグナルファイルから利用可能な日付を取得する"""
    signal_dir = DATA_DIR / "signals"
    files = sorted(signal_dir.glob("20*.parquet"), reverse=True)
    return [f.stem for f in files]


# --- ヘッダー ---

def render_header(market_df: pd.DataFrame, report_date: str):
    """市場指標メトリクスを表示する"""
    if market_df.empty:
        return

    target = pd.to_datetime(report_date)
    latest = market_df[market_df["date"] <= target]
    if latest.empty:
        return

    latest_date = latest["date"].max()
    day_data = latest[latest["date"] == latest_date]

    indicators = ["nikkei225", "sp500", "usdjpy", "us10y", "vix"]
    labels = {"nikkei225": "Nikkei 225", "sp500": "S&P 500", "usdjpy": "USD/JPY", "us10y": "US 10Y", "vix": "VIX"}

    cols = st.columns(len(indicators))
    for col, ind in zip(cols, indicators):
        row = day_data[day_data["indicator"] == ind]
        if row.empty:
            continue
        r = row.iloc[0]
        val = f"{r['value']:,.2f}" if ind in ("usdjpy", "us10y", "vix") else f"{r['value']:,.0f}"
        delta = f"{r['change_pct']:+.2f}%" if pd.notna(r["change_pct"]) else None
        col.metric(labels.get(ind, ind), val, delta)


# --- Tab 1: 概況 ---

def render_overview(market_df: pd.DataFrame, scored: pd.DataFrame, name_map: dict, report_date: str):
    # コメンタリー
    from stock_report.reporter.html import _generate_commentary, _build_market_metrics
    highlights = _generate_commentary(date.fromisoformat(report_date),
                                       _build_market_metrics(date.fromisoformat(report_date)))
    if highlights:
        st.info("\n".join(highlights))

    col1, col2 = st.columns([3, 2])

    # セクターヒートマップ
    with col1:
        st.subheader("Sector Heatmap")
        fundamentals = load_fundamentals()
        if not scored.empty and not fundamentals.empty:
            merged = scored.merge(fundamentals[["ticker", "sector", "market_cap"]], on="ticker", how="left",
                                  suffixes=("", "_f"))
            merged["sector"] = merged["sector"].fillna(merged.get("sector_f", ""))
            merged["market_cap"] = merged["market_cap"].fillna(merged.get("market_cap_f", 0))
            sector_df = merged.dropna(subset=["sector"]).copy()
            sector_df = sector_df[sector_df["market_cap"] > 0]

            if not sector_df.empty:
                # 日次リターンを近似（return_6mしかないので、直近の変動で代替）
                sector_df["name"] = sector_df["ticker"].map(name_map).fillna(sector_df["ticker"])
                sector_df["label"] = sector_df["name"].str[:8]
                # composite_scoreで色付け
                fig = px.treemap(
                    sector_df.head(200), path=["sector", "label"], values="market_cap",
                    color="composite_score", color_continuous_scale="Viridis",
                    hover_data={"composite_score": ":.1f"},
                )
                fig.update_layout(**CHART_LAYOUT, height=400)
                st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)

    # 主要指標スパークライン
    with col2:
        st.subheader("Indicators (20D)")
        for ind in ["nikkei225", "sp500", "usdjpy", "vix"]:
            ind_data = market_df[market_df["indicator"] == ind].sort_values("date").tail(20)
            if ind_data.empty:
                continue
            fig = go.Figure(go.Scatter(
                x=ind_data["date"], y=ind_data["value"],
                mode="lines", line=dict(width=2, color="#6C9BCF"),
            ))
            fig.update_layout(
                height=60, margin=dict(l=0, r=0, t=18, b=0),
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(visible=False), yaxis=dict(visible=False),
                title=dict(text=ind, font=dict(size=11, color="#8b8b8b")),
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)


# --- Tab 2: スクリーニング ---

def render_screening(signals: pd.DataFrame, scored: pd.DataFrame, name_map: dict):
    if signals.empty:
        st.warning("シグナルデータなし")
        return

    sub_tabs = st.tabs(["All", "Value+Quality", "Momentum", "Dividend", "Convergence"])

    screen_filters = [None, "screen_a", "screen_b", "screen_c", "convergence"]

    for tab, screen_type in zip(sub_tabs, screen_filters):
        with tab:
            df = signals.copy()
            if screen_type:
                df = df[df["screen_type"] == screen_type]

            if df.empty:
                st.info("該当なし")
                continue

            df = df.sort_values("composite_score", ascending=False)
            df["name"] = df["ticker"].map(name_map).fillna("")

            # テーブル表示
            display_df = df[["ticker", "name", "screen_type", "composite_score", "detail"]].copy()
            display_df.columns = ["Ticker", "Name", "Screen", "Score", "Detail"]

            st.dataframe(
                display_df,
                column_config={
                    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
                },
                hide_index=True,
                use_container_width=True,
                height=min(len(display_df) * 35 + 38, 600),
            )
            st.caption(f"{len(df)} signals")

    # 散布図
    if not scored.empty:
        st.subheader("Value vs Momentum")
        plot_df = scored.dropna(subset=["value_score", "momentum_score"]).copy()
        if not plot_df.empty:
            plot_df["name"] = plot_df["ticker"].map(name_map).fillna(plot_df["ticker"])
            plot_df["market_cap"] = plot_df["market_cap"].fillna(0).clip(lower=0)
            plot_df = plot_df[plot_df["market_cap"] > 0]
            fig = px.scatter(
                plot_df, x="value_score", y="momentum_score",
                color="composite_score", size="market_cap",
                hover_name="name", hover_data={"ticker": True, "composite_score": ":.1f"},
                color_continuous_scale="Viridis", size_max=30,
            )
            fig.add_hline(y=50, line_dash="dot", line_color="#444")
            fig.add_vline(x=50, line_dash="dot", line_color="#444")
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=500, margin=dict(l=0, r=0, t=30, b=0),
                xaxis=dict(title="Value Score", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
                yaxis=dict(title="Momentum Score", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)


# --- Tab 3: 銘柄詳細 ---

def render_stock_detail(name_map: dict):
    """個別銘柄のローソク足チャート + 指標を表示する"""
    ticker = st.text_input("銘柄コード（例: 7203.T, AAPL）", value="7203.T")
    if not ticker:
        return

    prices = load_prices(ticker)
    if prices.empty:
        st.error(f"{ticker} のデータが見つからない")
        return

    name = name_map.get(ticker, "")
    st.subheader(f"{ticker} {name}")

    # ローソク足 + 出来高 + RSI の3段チャート
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=("Price", "Volume", "RSI"),
    )

    # ローソク足
    fig.add_trace(go.Candlestick(
        x=prices["date"], open=prices["open"], high=prices["high"],
        low=prices["low"], close=prices["close"],
        increasing_line_color="#FF4444", decreasing_line_color="#4488FF",
        name="OHLC",
    ), row=1, col=1)

    # 移動平均線
    for col_name, color, label in [("sma_25", "#FFD93D", "SMA25"), ("sma_75", "#00D4AA", "SMA75"), ("sma_200", "#FF6B6B", "SMA200")]:
        if col_name in prices.columns:
            fig.add_trace(go.Scatter(
                x=prices["date"], y=prices[col_name],
                mode="lines", line=dict(width=1, color=color), name=label,
            ), row=1, col=1)

    # 出来高
    fig.add_trace(go.Bar(
        x=prices["date"], y=prices["volume"],
        marker_color="#6C9BCF", opacity=0.5, name="Volume",
    ), row=2, col=1)

    # RSI
    if "rsi_14" in prices.columns:
        fig.add_trace(go.Scatter(
            x=prices["date"], y=prices["rsi_14"],
            mode="lines", line=dict(width=1.5, color="#E67E22"), name="RSI",
        ), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#FF4444", line_width=0.5, row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#4488FF", line_width=0.5, row=3, col=1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=700, showlegend=False,
        xaxis_rangeslider_visible=False,
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)

    # ファンダメンタル指標
    fundamentals = load_fundamentals()
    if not fundamentals.empty:
        fund_row = fundamentals[fundamentals["ticker"] == ticker]
        if not fund_row.empty:
            f = fund_row.iloc[0]
            cols = st.columns(6)
            cols[0].metric("PER", f"{f.get('per', 0):.1f}" if pd.notna(f.get("per")) else "-")
            cols[1].metric("PBR", f"{f.get('pbr', 0):.2f}" if pd.notna(f.get("pbr")) else "-")
            cols[2].metric("配当利回り", f"{f.get('dividend_yield', 0):.1f}%" if pd.notna(f.get("dividend_yield")) else "-")
            cols[3].metric("ROE", f"{f.get('roe', 0):.1f}%" if pd.notna(f.get("roe")) else "-")
            cols[4].metric("Sector", str(f.get("sector", "-"))[:15])
            cols[5].metric("時価総額", f"{f.get('market_cap', 0)/1e9:.0f}B" if pd.notna(f.get("market_cap")) else "-")


# --- メイン ---

def main():
    st.set_page_config(page_title="StockChecker", layout="wide", initial_sidebar_state="expanded")

    # サイドバー
    with st.sidebar:
        st.title("StockChecker")
        available_dates = get_available_dates()
        if not available_dates:
            st.error("データなし。先にdaily_batch.pyを実行してね")
            return

        selected_date = st.selectbox("レポート日付", available_dates)

    # データ読み込み
    name_map = load_name_map()
    market_df = load_market_data()
    signals = load_signals(selected_date)
    scored = load_scored(selected_date)

    # ヘッダー
    render_header(market_df, selected_date)

    # タブ
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["概況", "スクリーニング", "精度検証", "ウォッチリスト", "カレンダー", "銘柄詳細"])

    with tab1:
        render_overview(market_df, scored, name_map, selected_date)

    with tab2:
        render_screening(signals, scored, name_map)

    with tab3:
        render_accuracy()

    with tab4:
        render_watchlist(name_map, selected_date)

    with tab5:
        render_calendar(name_map)

    with tab6:
        render_stock_detail(name_map)


# --- Tab 3: 精度検証 ---

def render_accuracy():
    from stock_report.analyzer.accuracy import compute_accuracy, compute_accuracy_by_score_band

    st.subheader("Screen Accuracy (Backtest)")

    accuracy = compute_accuracy()
    if accuracy.empty:
        st.warning("バックテストデータなし。`uv run python -m stock_report.analyzer.backtest` を実行してね")
        return

    # スクリーン別の勝率テーブル
    screen_labels = {"screen_a": "Value+Quality", "screen_b": "Momentum", "screen_c": "Dividend", "convergence": "Convergence"}
    accuracy["Screen"] = accuracy["screen_type"].map(screen_labels)

    st.dataframe(
        accuracy[["Screen", "total_signals", "win_rate_5d", "win_rate_10d", "win_rate_20d",
                  "avg_return_5d", "avg_return_10d", "avg_return_20d"]].rename(columns={
            "total_signals": "Signals", "win_rate_5d": "Win% 5D", "win_rate_10d": "Win% 10D",
            "win_rate_20d": "Win% 20D", "avg_return_5d": "Avg 5D", "avg_return_10d": "Avg 10D",
            "avg_return_20d": "Avg 20D",
        }),
        hide_index=True, use_container_width=True,
    )

    # リターン分布ヒストグラム
    st.subheader("Return Distribution")
    try:
        bt = pd.read_parquet(DATA_DIR / "signals" / "backtest.parquet")
    except FileNotFoundError:
        return

    period = st.selectbox("Period", ["5d", "10d", "20d"], index=1)
    col_name = f"return_{period}"

    fig = px.histogram(
        bt.dropna(subset=[col_name]), x=col_name, color="screen_type",
        nbins=50, barmode="overlay", opacity=0.7,
        labels={col_name: f"Return ({period})", "screen_type": "Screen"},
        color_discrete_map={"screen_a": "#9B59B6", "screen_b": "#00D4AA", "screen_c": "#E67E22", "convergence": "#FFD93D"},
    )
    fig.add_vline(x=0, line_dash="solid", line_color="#FF4444", line_width=1)
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=350, margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)

    # スコア帯別勝率
    st.subheader("Win Rate by Score Band")
    score_band = compute_accuracy_by_score_band()
    if not score_band.empty:
        fig2 = px.bar(
            score_band, x="score_band", y=[f"win_rate_{period}"],
            labels={"value": f"Win Rate ({period})", "score_band": "Score Band"},
            barmode="group",
        )
        fig2.add_hline(y=50, line_dash="dot", line_color="#FF4444", line_width=1, annotation_text="50%")
        fig2.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=300, margin=dict(l=0, r=0, t=30, b=0), showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True, config=CHART_CONFIG)


# --- Tab 4: ウォッチリスト ---

def render_watchlist(name_map: dict, selected_date: str):
    from stock_report.watchlist import get_holdings, get_watching, check_thesis

    # テーゼチェック
    st.subheader("Thesis Check")
    alerts = check_thesis(date.fromisoformat(selected_date))
    if alerts:
        for alert in alerts:
            ticker = alert["ticker"]
            name = name_map.get(ticker, "")
            pnl = alert.get("pnl_pct")
            pnl_str = f"({pnl:+.1f}%)" if pnl is not None else ""

            with st.container():
                st.warning(f"**{ticker} {name}** {pnl_str}")
                st.caption(f"テーゼ: {alert['thesis']}")
                for reason in alert["reasons"]:
                    st.markdown(f"- {reason}")
    else:
        st.success("保有銘柄に投資テーゼを変えるべき変化はなし")

    st.divider()

    # 保有銘柄
    st.subheader("Holdings")
    holdings = get_holdings()
    if holdings:
        for h in holdings:
            ticker = h["ticker"]
            name = name_map.get(ticker, "")
            prices = load_prices(ticker)

            if not prices.empty:
                latest = prices.iloc[-1]
                close = latest["close"]
                buy_price = h.get("buy_price", 0)
                pnl = (close - buy_price) / buy_price * 100 if buy_price else 0

                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                col1.markdown(f"**{ticker}** {name}")
                col2.metric("現在値", f"¥{close:,.0f}")
                col3.metric("損益", f"{pnl:+.1f}%")
                col4.caption(h.get("thesis", ""))

                # スパークライン
                spark_data = prices.tail(30)
                fig = go.Figure(go.Scatter(
                    x=spark_data["date"], y=spark_data["close"],
                    mode="lines", line=dict(width=1.5, color="#00D4AA" if pnl >= 0 else "#FF6B6B"),
                ))
                # 購入価格の水平線
                if buy_price:
                    fig.add_hline(y=buy_price, line_dash="dot", line_color="#FFD93D", line_width=0.8)
                fig.update_layout(
                    height=80, margin=dict(l=0, r=0, t=0, b=0),
                    template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)
                st.divider()
    else:
        st.info("保有銘柄なし。config/watchlist.toml で追加してね")

    # 注目銘柄
    st.subheader("Watching")
    watching = get_watching()
    if watching:
        for w in watching:
            ticker = w["ticker"]
            name = name_map.get(ticker, "")
            reason = w.get("reason", "")

            # シグナルチェック
            try:
                signals = load_signals(selected_date)
                has_signal = ticker in signals["ticker"].values if not signals.empty else False
            except Exception:
                has_signal = False

            col1, col2 = st.columns([3, 1])
            label = f"**{ticker}** {name}"
            if has_signal:
                label += " :green[Signal]"
            col1.markdown(label)
            col2.caption(reason)
    else:
        st.info("注目銘柄なし")


# --- Tab 5: カレンダー ---

def render_calendar(name_map: dict):
    from stock_report.watchlist import get_earnings_calendar, get_all_watchlist_tickers

    st.subheader("Earnings Calendar")
    st.caption("ウォッチリスト銘柄の決算・配当イベント")

    with st.spinner("決算カレンダー取得中..."):
        events = get_earnings_calendar()

    if not events:
        st.info("直近のイベントなし")
        return

    # テーブル表示
    df = pd.DataFrame(events)
    df["name"] = df["ticker"].map(name_map).fillna("")
    df = df[["date", "ticker", "name", "event"]]
    df.columns = ["Date", "Ticker", "Name", "Event"]

    st.dataframe(df, hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
