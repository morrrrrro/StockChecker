# UI設計書

## 概要

2つの閲覧インターフェースを提供する。

1. **静的HTMLレポート（GitHub Pages）** — メインの閲覧手段。毎日自動生成・公開。PC・スマホ対応。
2. **Streamlitダッシュボード（ローカル）** — インタラクティブな深掘り分析用。フィルタ・ドリルダウンが可能。

いずれも「Do I need to act right now?（今すぐ行動すべきか？）」に3秒で答えられるUIを目指す。

---

## Part 1: 静的HTMLレポート（GitHub Pages）

### 設計方針

- 単一HTMLファイルで完結（外部CSS/JS依存なし）
- Plotlyチャートをインラインで埋め込み（インタラクティブなまま）
- レスポンシブデザイン（スマホでの朝チェックを想定）
- ダークテーマ

### レポート構成

SPEC.mdの7セクション構成に準拠:

```html
<body>
  <!-- ① 市場環境サマリー -->
  <section id="market-summary">
    指標カード × 6（日経/TOPIX/USD-JPY/米10年債/VIX/S&P500）
    前日比のカラーコーディング
  </section>

  <!-- ② 今日のポイント -->
  <section id="highlights">
    2-3行のテキスト
  </section>

  <!-- ③ セクター動向 -->
  <section id="sector">
    Plotly Treemap（インタラクティブ、タップで詳細表示）
  </section>

  <!-- ④ スクリーニング結果 -->
  <section id="screening">
    Screen A / B / C のタブ切り替え（CSS only）
    結果テーブル + スコアバー
    収束シグナル強調表示
  </section>

  <!-- ⑤ ウォッチリスト -->
  <section id="watchlist">
    シグナルバッジ付きテーブル
    スパークラインSVG
  </section>

  <!-- ⑥ カタリスト -->
  <section id="catalysts">
    今週の決算・経済指標リスト
  </section>

  <!-- ⑦ テーゼチェック -->
  <section id="thesis-check">
    変化ありの銘柄のみ表示（なければ非表示）
  </section>
</body>
```

### アーカイブ

```
reports/
├── index.html          # 最新レポートへのリダイレクト + 過去一覧
├── 2026-04-08.html
├── 2026-04-07.html
└── ...
```

`index.html` はバッチ実行時に自動更新される。

---

## Part 2: Streamlitダッシュボード（ローカル深掘り用）

## 全体レイアウト

```
┌──────────────────────────────────────────────────────────┐
│  HEADER                                                   │
│  [日経225 ▲38,450] [TOPIX ▼2,680] [USD/JPY 154.20] [VIX] │
│  st.metric × 4-6                                         │
├──────────┬───────────────────────────────────────────────┤
│          │  TABS                                          │
│ SIDEBAR  │  [概況] [スクリーニング] [ウォッチリスト] [カレンダー] │
│          │                                                │
│ 日付選択  │  ┌─────────────────────────────────────────┐  │
│ セクター  │  │                                         │  │
│ フィルタ  │  │  タブごとのコンテンツ                      │  │
│ スコア   │  │                                         │  │
│ 閾値     │  │                                         │  │
│          │  └─────────────────────────────────────────┘  │
└──────────┴───────────────────────────────────────────────┘
```

## ヘッダー（常時表示）

`st.metric` を横並びで配置する。全タブ共通。

```python
col1, col2, col3, col4 = st.columns(4)
col1.metric("日経225", "38,450", "-1.2%")
col2.metric("TOPIX", "2,680", "-0.8%")
col3.metric("USD/JPY", "154.20", "+0.3%")
col4.metric("VIX", "18.5", "-2.1%")
```

- `delta_color="normal"` で上昇=緑、下落=赤（Streamlitデフォルト）
- 日本市場慣習（赤=上昇）はチャート側で対応し、metricはStreamlit標準に従う

## サイドバー（グローバルフィルタ）

全タブに影響する共通フィルタをサイドバーに配置する。

```python
with st.sidebar:
    selected_date = st.date_input("レポート日付")
    sectors = st.multiselect("セクター", options=sector_list)
    min_score = st.slider("最低スコア", 0, 100, 50)
    min_volume = st.slider("最低出来高倍率", 1.0, 5.0, 1.5)
```

## タブ構成

### Tab 1: 概況

**目的**: 市場全体の状況を30秒で把握する

#### 上段: 今日のポイント

`st.info` または `st.markdown` で2-3行の要約を表示。

#### 中段: 2カラムレイアウト

```
┌─────────────────────┐ ┌─────────────────────────┐
│ セクターヒートマップ  │ │ 主要指標スパークライン   │
│ (Plotly Treemap)     │ │ (5日間の推移 × 6指標)   │
│                      │ │                         │
│ サイズ = 時価総額     │ │ 日経225  ~~~~~~~~       │
│ 色 = 日次リターン     │ │ TOPIX   ~~~~~~~~       │
│                      │ │ USD/JPY ~~~~~~~~       │
└─────────────────────┘ └─────────────────────────┘
```

#### 下段: 値上がり/値下がりランキング

上位5銘柄ずつの簡易テーブル。

### Tab 2: スクリーニング

**目的**: 買い目の銘柄を定量的に確認する

#### サブタブ構成

```python
sub_a, sub_b, sub_c, sub_all = st.tabs([
    "Value+Quality", "Momentum", "Dividend", "収束シグナル"
])
```

#### 各サブタブの内容

**スクリーニング結果テーブル**

`st.dataframe` に `column_config` でスパークラインを内蔵する。

```python
st.dataframe(df, column_config={
    "ticker": st.column_config.TextColumn("銘柄"),
    "company": st.column_config.TextColumn("企業名"),
    "close": st.column_config.NumberColumn("株価", format="¥%d"),
    "composite_score": st.column_config.ProgressColumn("スコア", min_value=0, max_value=100),
    "sparkline": st.column_config.LineChartColumn("5日チャート"),
    "signal_state": st.column_config.TextColumn("状態"),
    "rr_ratio": st.column_config.NumberColumn("R:R", format="%.2f"),
})
```

**散布図（バリュー vs モメンタム）**

`px.scatter` で4象限マッピング。

```
            高モメンタム
                │
    割高モメンタム │ 優良モメンタム ← 注目
   ─────────────┼─────────────
    回避         │ バリュートラップ?
                │
            低モメンタム
   低バリュー ←──┼──→ 高バリュー
```

- ドットサイズ: 時価総額
- ドットカラー: セクター
- ホバー: 企業名、スコア詳細、直近シグナル

**収束シグナルタブ**

複数スクリーンに同時出現する銘柄をハイライト。ベン図的な表現または強調テーブル。

### Tab 3: ウォッチリスト

**目的**: 監視中・保有中の銘柄の状況を確認する

#### 上段: テーゼチェック（変化ありのみ表示）

変化がある銘柄だけを `st.warning` で表示。変化なしなら非表示。

```python
if thesis_changes:
    for change in thesis_changes:
        st.warning(f"{change.ticker}: {change.description}")
else:
    st.success("保有銘柄に投資テーゼを変えるべき変化はなし")
```

#### 中段: ウォッチリストテーブル

各銘柄の行に以下を表示:
- シグナルバッジ（ライフサイクル状態）
- 確信度ドット（●●●○○）
- スパークライン
- スコア（Value / Quality / Momentum / Risk）

#### 下段: 個別銘柄詳細（Expander）

```python
with st.expander(f"7203 トヨタ自動車", expanded=False):
    # ローソク足チャート（make_subplots: 価格 + 出来高 + RSI）
    # ファンダメンタル指標テーブル
    # シグナル履歴
```

`make_subplots` で3段構成:
1. ローソク足 + 移動平均線
2. 出来高バー
3. RSI / MACD（切り替え可能）

### Tab 4: カレンダー

**目的**: 今後1-2週間のカタリストを把握する

#### 上段: 決算発表カレンダー

日付ごとに決算発表予定の銘柄をバッジで表示。
バッジの色でシグナル状況を示す（ウォッチリスト銘柄は強調）。

#### 下段: 経済指標・イベント

```
4/10(木) CPI(米) 予想: 3.2% 前回: 3.1%
4/11(金) SQ日
4/14(月) 日銀短観
```

## 色設計

### ダークテーマベース

Streamlitのダークテーマを基本とする。

| 用途 | カラーコード | 説明 |
|---|---|---|
| 背景 | `#0E1117` | Streamlitダークテーマデフォルト |
| 上昇 | `#FF4444` | 赤（日本市場慣習: チャート内） |
| 下落 | `#4488FF` | 青（日本市場慣習: チャート内） |
| ハイライト | `#FFD93D` | アンバー（新規シグナル） |
| 情報 | `#6C9BCF` | スチールブルー |
| ニュートラル | `#8B8B8B` | グレー |

### Plotlyチャート共通設定

```python
CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, t=30, b=0),
    xaxis=dict(showgrid=False),
    yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
)
CHART_CONFIG = dict(displayModeBar=False)
```

### セクターヒートマップの色

`RdBu` (Red-Blue) 分岐カラースケールを使用。
中央値=0 として、正=赤（上昇）、負=青（下落）。

## アラート階層設計

日次レポートの情報には3段階の重要度がある。

### Tier 1: フルアラート（1日0-2件）

```python
st.error("⚠ 7203 トヨタ: ストップロス水準到達 (¥2,100)")
```

対象:
- ストップロス水準到達
- 保有銘柄の決算サプライズ（大幅乖離）
- サーキットブレーカー / ストップ高・安

### Tier 2: ハイライト（1日5-8件）

シグナルバッジとしてインライン表示。

対象:
- ウォッチリスト銘柄の新規シグナル検出
- 出来高2倍超の異常活動
- テクニカル水準ブレイク（移動平均線、サポート/レジスタンス）

### Tier 3: フットノート（Expander内）

```python
with st.expander("その他の通知"):
    st.caption("6758 ソニー: RSIが65に上昇（70接近、モメンタム減衰注意）")
```

対象:
- シグナル接近中（未発火）
- 出来高やや増加
- セクター内連動（保有銘柄への間接影響）

## パフォーマンス考慮

### キャッシュ戦略

```python
@st.cache_data(ttl=3600)  # 1時間キャッシュ（日次レポートなのでDBは日中変わらない）
def load_daily_report(date):
    ...
```

### 実用上限

| 要素 | 快適範囲 | 上限 |
|---|---|---|
| Plotlyチャート/ページ | 8-12 | 20超でラグ |
| DataFrameの表示行数 | 100-500 | 5000超でスクロール重い |
| タブ数 | 4-5 | 7超でUX悪化 |

### 最適化手法

- `st.cache_data` で全データ取得・計算をキャッシュ
- Expander内のチャートは展開時のみレンダリング
- スパークラインは `st.column_config.LineChartColumn` を使用（個別Plotlyチャートより高速）
- `st.fragment`（Streamlit 1.33+）で部分再描画
