# 技術設計書

## 技術スタック

| カテゴリ | 技術 | バージョン | 用途 |
|---|---|---|---|
| 言語 | Python | 3.13.3 | 全コンポーネント |
| 依存管理 | uv | 0.10.9 | パッケージ管理・仮想環境 |
| 株価データ | yfinance | latest | OHLCV・基本ファンダメンタル取得 |
| 財務データ | EDINET API + edinet-tools | latest | 有価証券報告書XBRL解析（F-Score等） |
| テクニカル分析 | pandas-ta | latest | RSI, MACD, ボリンジャーバンド等 |
| クエリエンジン | DuckDB | latest | Parquet直読み・OLAP分析・パーセンタイルランク算出 |
| ローカルUI | Streamlit | latest | インタラクティブダッシュボード（ローカル深掘り用） |
| 静的レポート | Plotly + Jinja2 | latest | GitHub Pages用HTML生成 |
| チャート描画 | Plotly | latest | ローソク足、Treemap、散布図等 |
| HTTP通信 | httpx | latest | EDINET API通信 |
| データ保存 | Parquet | - | 列指向圧縮フォーマット、gitにcommit |
| スケジューリング | GitHub Actions | - | 日次バッチ（クラウド実行） |
| レポート公開 | GitHub Pages | - | 静的HTMLレポートのホスティング |

## プロジェクトディレクトリ構成

```
stock-report/
├── pyproject.toml              # uv プロジェクト定義
├── CLAUDE.md                   # Claude Code プロジェクト設定
├── docs/                       # 仕様書・設計書
│   ├── SPEC.md
│   ├── ARCHITECTURE.md
│   ├── SCREENING.md
│   ├── UI_DESIGN.md
│   └── IMPLEMENTATION_PLAN.md
├── .github/
│   └── workflows/
│       └── daily_report.yml    # GitHub Actions 日次バッチ
├── src/
│   └── stock_report/
│       ├── __init__.py
│       ├── fetcher/            # データ取得レイヤー
│       │   ├── __init__.py
│       │   ├── price.py        # yfinance OHLCV取得
│       │   ├── fundamental.py  # yfinance .info + EDINET財務データ
│       │   └── market.py       # 指数・為替・債券利回り取得
│       ├── analyzer/           # 分析レイヤー
│       │   ├── __init__.py
│       │   ├── technical.py    # テクニカル指標算出（pandas-ta）
│       │   ├── scoring.py      # マルチファクタースコアリング
│       │   ├── screener.py     # 3スクリーン実行
│       │   └── signal.py       # シグナルライフサイクル管理
│       ├── reporter/           # レポート生成レイヤー
│       │   ├── __init__.py
│       │   ├── daily.py        # 日次レポートデータ組み立て
│       │   └── html.py         # 静的HTMLレポート生成（Plotly + Jinja2）
│       ├── db.py               # DuckDB クエリエンジン（Parquet直読み）
│       └── app.py              # Streamlit ダッシュボード（ローカル用）
├── templates/
│   └── report.html             # Jinja2テンプレート（GitHub Pages用）
├── data/                       # Parquetデータ（gitで管理・蓄積）
│   ├── prices/
│   │   ├── 2026-04.parquet     # 月単位で分割
│   │   └── ...
│   ├── market/
│   │   ├── 2026-04.parquet
│   │   └── ...
│   ├── fundamentals/
│   │   └── latest.parquet      # 最新のファンダメンタルデータ
│   └── signals/
│       ├── 2026-04-08.parquet  # 日単位のスクリーニング結果
│       └── lifecycle.parquet   # シグナルライフサイクル状態
├── reports/                    # 生成された静的HTMLレポート（GitHub Pages用）
│   ├── index.html              # 最新レポートへのリダイレクト
│   ├── 2026-04-08.html
│   └── ...
├── config/
│   └── watchlist.toml          # 監視銘柄・ポートフォリオ定義
└── scripts/
    └── daily_batch.py          # バッチスクリプト（GitHub Actionsから呼ぶ）
```

## データフロー

### 日次バッチ（GitHub Actions）

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions (毎日 18:00 JST / 09:00 UTC)                    │
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌──────────────────┐  │
│  │ yfinance    │────→│ fetcher/    │────→│ data/prices/     │  │
│  │ (OHLCV)     │     │ price.py    │     │ 2026-04.parquet  │  │
│  ├─────────────┤     ├─────────────┤     ├──────────────────┤  │
│  │ yfinance    │────→│ fetcher/    │────→│ data/market/     │  │
│  │ (指数/為替)  │     │ market.py   │     │ 2026-04.parquet  │  │
│  ├─────────────┤     ├─────────────┤     ├──────────────────┤  │
│  │ EDINET API  │────→│ fetcher/    │────→│ data/fundamentals│  │
│  │ (XBRL)      │     │ fundamental │     │ latest.parquet   │  │
│  └─────────────┘     └─────────────┘     └────────┬─────────┘  │
│                                                    │            │
│                                                    ▼            │
│                                          ┌──────────────────┐  │
│                                          │ DuckDB           │  │
│                                          │ (クエリエンジン)   │  │
│                                          │ Parquet直読み     │  │
│                                          └────────┬─────────┘  │
│                                                    │            │
│                                                    ▼            │
│                                          ┌──────────────────┐  │
│                                          │ analyzer/        │  │
│                                          │ technical.py     │  │
│                                          │ scoring.py       │  │
│                                          │ screener.py      │  │
│                                          │ signal.py        │  │
│                                          └────────┬─────────┘  │
│                                                    │            │
│                                          ┌─────────┴─────────┐ │
│                                          ▼                   ▼  │
│                                 ┌──────────────┐  ┌───────────┐│
│                                 │ data/signals/│  │ reporter/ ││
│                                 │ *.parquet    │  │ html.py   ││
│                                 └──────────────┘  └─────┬─────┘│
│                                                         │      │
│                                                         ▼      │
│                                                  ┌───────────┐ │
│                                                  │ reports/  │ │
│                                                  │ *.html    │ │
│                                                  └───────────┘ │
│                                                                  │
│  git commit & push (data/ + reports/)                            │
│  GitHub Pages デプロイ (reports/)                                 │
└─────────────────────────────────────────────────────────────────┘
```

### ローカル閲覧（Streamlit）

```
git pull → Parquet読み込み → DuckDB(インメモリ) → Streamlit表示
```

### バッチ処理フロー（daily_batch.py）

1. `fetcher/price.py` — 対象銘柄のOHLCVデータを取得 → `data/prices/YYYY-MM.parquet` に追記
2. `fetcher/market.py` — 指数・為替・債券データを取得 → `data/market/YYYY-MM.parquet` に追記
3. `fetcher/fundamental.py` — ファンダメンタルデータを取得/更新 → `data/fundamentals/latest.parquet` を更新
4. `analyzer/technical.py` — テクニカル指標を算出（DuckDBでParquetを読み、結果をParquetに書き戻し）
5. `analyzer/scoring.py` — マルチファクタースコアを算出
6. `analyzer/screener.py` — 3スクリーンを実行 → `data/signals/YYYY-MM-DD.parquet` に保存
7. `analyzer/signal.py` — シグナルライフサイクルを更新 → `data/signals/lifecycle.parquet` を更新
8. `reporter/html.py` — 静的HTMLレポート生成 → `reports/YYYY-MM-DD.html` に出力
9. `reports/index.html` を最新日付にリダイレクト更新

## データ保存設計（Parquet）

### なぜParquetか

- 列指向圧縮で小サイズ（日経225銘柄の1日分 ≈ 10-20KB）
- DuckDBがネイティブに直読み可能（`SELECT * FROM 'data/prices/*.parquet'`）
- gitで差分管理可能（バイナリだが小サイズなので実用上問題なし）
- pandasで直接読み書き可能

### ファイル分割戦略

| データ種別 | 分割単位 | 理由 |
|---|---|---|
| prices | 月 (`YYYY-MM.parquet`) | 日次追記の頻度と1ファイルあたりのサイズのバランス |
| market | 月 (`YYYY-MM.parquet`) | pricesと同様 |
| fundamentals | 単一ファイル (`latest.parquet`) | 四半期更新のため分割不要 |
| signals | 日 (`YYYY-MM-DD.parquet`) | 日次レポートと1:1対応 |
| lifecycle | 単一ファイル (`lifecycle.parquet`) | 現在の状態のみ保持 |

### DuckDBクエリ例

```python
import duckdb

# 全期間の株価データをクエリ（Parquetのglobパターン）
duckdb.sql("""
    SELECT * FROM 'data/prices/*.parquet'
    WHERE ticker = '7203.T'
    ORDER BY date DESC
    LIMIT 200
""")

# パーセンタイルランク算出
duckdb.sql("""
    SELECT
        ticker,
        close,
        PERCENT_RANK() OVER (ORDER BY per) AS value_rank,
        PERCENT_RANK() OVER (ORDER BY roe DESC) AS quality_rank
    FROM 'data/prices/*.parquet' p
    JOIN 'data/fundamentals/latest.parquet' f USING (ticker)
    WHERE p.date = CURRENT_DATE
""")
```

## Parquetスキーマ定義

### prices（日次株価 + テクニカル指標）

| カラム | 型 | 説明 |
|---|---|---|
| date | DATE | 取引日 |
| ticker | VARCHAR | 銘柄コード（例: 7203.T） |
| open | DOUBLE | 始値 |
| high | DOUBLE | 高値 |
| low | DOUBLE | 安値 |
| close | DOUBLE | 終値 |
| volume | INT64 | 出来高 |
| sma_25 | DOUBLE | 25日移動平均 |
| sma_75 | DOUBLE | 75日移動平均 |
| sma_200 | DOUBLE | 200日移動平均 |
| rsi_14 | DOUBLE | RSI(14) |
| macd | DOUBLE | MACD |
| macd_signal | DOUBLE | MACDシグナル |
| macd_hist | DOUBLE | MACDヒストグラム |
| bb_upper | DOUBLE | ボリンジャーバンド上限 |
| bb_middle | DOUBLE | ボリンジャーバンド中央 |
| bb_lower | DOUBLE | ボリンジャーバンド下限 |
| atr_14 | DOUBLE | ATR(14) |

### fundamentals（ファンダメンタルデータ）

| カラム | 型 | 説明 |
|---|---|---|
| ticker | VARCHAR | 銘柄コード |
| fiscal_year | INT32 | 会計年度 |
| per | DOUBLE | PER |
| pbr | DOUBLE | PBR |
| dividend_yield | DOUBLE | 配当利回り |
| roe | DOUBLE | ROE |
| market_cap | INT64 | 時価総額 |
| sector | VARCHAR | セクター |
| industry | VARCHAR | 業種 |
| ebit | INT64 | EBIT |
| enterprise_value | INT64 | EV |
| net_working_capital | INT64 | 正味運転資本 |
| net_fixed_assets | INT64 | 正味固定資産 |
| net_income | INT64 | 当期純利益 |
| total_assets | INT64 | 総資産 |
| operating_cf | INT64 | 営業CF |
| long_term_debt | INT64 | 長期負債 |
| current_ratio | DOUBLE | 流動比率 |
| shares_issued | INT64 | 発行済株式数 |
| gross_margin | DOUBLE | 粗利率 |
| revenue | INT64 | 売上高 |
| f_score | INT32 | Piotroski F-Score |
| earnings_yield | DOUBLE | 益利回り |
| roc | DOUBLE | 投下資本利益率 |

### market（市場指標）

| カラム | 型 | 説明 |
|---|---|---|
| date | DATE | 日付 |
| indicator | VARCHAR | 指標名 |
| value | DOUBLE | 値 |
| change_pct | DOUBLE | 前日比(%) |

### signals（日次スクリーニング結果）

| カラム | 型 | 説明 |
|---|---|---|
| date | DATE | 日付 |
| ticker | VARCHAR | 銘柄コード |
| screen_type | VARCHAR | スクリーン種別 |
| composite_score | DOUBLE | 総合スコア |
| value_score | DOUBLE | バリュースコア |
| quality_score | DOUBLE | クオリティスコア |
| momentum_score | DOUBLE | モメンタムスコア |
| risk_score | DOUBLE | リスクスコア |
| detail | VARCHAR | シグナル理由 |

### lifecycle（シグナルライフサイクル）

| カラム | 型 | 説明 |
|---|---|---|
| ticker | VARCHAR | 銘柄コード |
| signal_type | VARCHAR | シグナル種別 |
| first_detected | DATE | 初回検出日 |
| current_state | VARCHAR | 現在の状態 |
| days_active | INT32 | 継続日数 |
| score_history | VARCHAR | スコア推移（JSON） |
| last_updated | DATE | 最終更新日 |

## GitHub Actions ワークフロー

### `.github/workflows/daily_report.yml`

```yaml
name: Daily Stock Report

on:
  schedule:
    # 毎日 09:00 UTC = 18:00 JST
    - cron: '0 9 * * 1-5'  # 月〜金のみ
  workflow_dispatch:  # 手動実行も可能

permissions:
  contents: write
  pages: write
  id-token: write

jobs:
  generate-report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync

      - name: Run daily batch
        run: uv run python scripts/daily_batch.py
        env:
          EDINET_API_KEY: ${{ secrets.EDINET_API_KEY }}

      - name: Commit data and reports
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/ reports/
          git diff --staged --quiet || git commit -m "daily report: $(date +%Y-%m-%d)"
          git push

  deploy-pages:
    needs: generate-report
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: reports/

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

## 依存パッケージ

```toml
[project]
dependencies = [
    "yfinance",
    "pandas-ta",
    "duckdb",
    "streamlit",
    "plotly",
    "edinet-tools",
    "httpx",
    "jinja2",
    "pandas",
    "numpy",
    "pyarrow",
]
```

## 設計方針

- **各モジュールは独立して実行可能**: fetcherだけ、analyzerだけ、のように個別実行できる
- **Parquetをデータハブとする**: モジュール間のデータ受け渡しはParquetファイル経由
- **DuckDBはクエリエンジンのみ**: 永続的なDBファイルは持たず、Parquetを直読みする
- **冪等性**: バッチを複数回実行しても安全（同一日の既存データは上書き）
- **GitHub Actions + GitHub Pages**: PC起動状態に依存しない自動実行と閲覧
- **Streamlitはローカル深掘り用**: インタラクティブ分析が必要な時だけ使う
