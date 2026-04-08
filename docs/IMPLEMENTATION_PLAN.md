# 実装計画書

## フェーズ概要

| Phase | 内容 | 依存 | 完了条件 |
|---|---|---|---|
| 1 | プロジェクト初期化 + データ取得 | なし | yfinanceでOHLCVをParquetに保存できる |
| 2 | テクニカル分析 + スクリーニング | Phase 1 | 3スクリーンの結果がParquetに出力される |
| 3 | 静的HTMLレポート生成 | Phase 2 | HTMLレポートが生成される |
| 4 | GitHub Actions + GitHub Pages | Phase 3 | 日次自動実行 + レポート自動公開 |
| 5 | Streamlitダッシュボード（ローカル深掘り用） | Phase 2 | ローカルでインタラクティブ閲覧できる |
| 6 | EDINET連携（ファンダメンタル強化） | Phase 1 | F-Score・Magic Formula指標が算出できる |
| 7 | ウォッチリスト + テーゼチェック + カレンダー | Phase 5 | 全タブ・全セクションが機能する |

## Phase 1: プロジェクト初期化 + データ取得

### タスク

1. **uv プロジェクト初期化**
   - `uv init` でプロジェクト作成
   - `pyproject.toml` に依存パッケージを追加
   - `src/stock_report/` パッケージ構成を作成

2. **Parquet I/O + DuckDBクエリエンジン（`db.py`）**
   - DuckDBインメモリ接続（Parquet直読み）
   - Parquet読み書きヘルパー関数
   - 月別Parquetファイルへの追記ロジック

3. **株価データ取得（`fetcher/price.py`）**
   - yfinanceで日経225構成銘柄のOHLCVを取得
   - `data/prices/YYYY-MM.parquet` に保存
   - 銘柄リストはconfig/watchlist.tomlから取得

4. **市場指標取得（`fetcher/market.py`）**
   - 日経225、TOPIX、S&P500、USD/JPY、米10年債、VIXの日次データ取得
   - `data/market/YYYY-MM.parquet` に保存

5. **ウォッチリスト設定（`config/watchlist.toml`）**
   - 初期ウォッチリスト銘柄の定義（日経225構成銘柄）
   - セクター分類の定義

### 完了条件

```bash
# 実行して日経225銘柄のデータがParquetに保存されることを確認
uv run python -m stock_report.fetcher.price
uv run python -m stock_report.fetcher.market

# DuckDBでParquetを直接クエリして確認
uv run python -c "
import duckdb
print(duckdb.sql(\"SELECT count(*) FROM 'data/prices/*.parquet'\").fetchone())
print(duckdb.sql(\"SELECT * FROM 'data/market/*.parquet' ORDER BY date DESC LIMIT 5\").fetchdf())
"
```

## Phase 2: テクニカル分析 + スクリーニング

### タスク

1. **テクニカル指標算出（`analyzer/technical.py`）**
   - pandas-taで以下を算出: SMA(25/75/200), RSI(14), MACD, ボリンジャーバンド, ATR(14)
   - prices Parquetに指標カラムを追加して書き戻し

2. **マルチファクタースコアリング（`analyzer/scoring.py`）**
   - パーセンタイルランク算出（DuckDBのウィンドウ関数活用）
   - Value / Quality / Momentum / Risk サブスコア計算
   - Composite Score算出（加重平均）
   - 階層型フィルター適用

3. **3スクリーン実行（`analyzer/screener.py`）**
   - Screen A: バリュー＋クオリティ
     - Phase 6のEDINET連携前は、yfinance .infoの指標（PER, PBR, ROE）で簡易版を実行
   - Screen B: モメンタムブレイクアウト
   - Screen C: 配当バリュー
   - `data/signals/YYYY-MM-DD.parquet` に保存
   - 収束シグナル（複数スクリーン該当）の検出

4. **シグナルライフサイクル管理（`analyzer/signal.py`）**
   - 日次状態遷移ロジック（新規→強化中→安定→減衰中→消失）
   - `data/signals/lifecycle.parquet` の更新

### 完了条件

```bash
# テクニカル指標の算出確認
uv run python -m stock_report.analyzer.technical

# スクリーニング実行
uv run python -m stock_report.analyzer.screener

# 結果確認
uv run python -c "
import duckdb
print(duckdb.sql(\"SELECT * FROM 'data/signals/$(date +%Y-%m-%d).parquet' ORDER BY composite_score DESC LIMIT 10\").fetchdf())
"
```

## Phase 3: 静的HTMLレポート生成

### タスク

1. **Jinja2テンプレート（`templates/report.html`）**
   - レスポンシブHTML（PC・スマホ対応）
   - ダークテーマ
   - Plotlyチャートの埋め込み（`fig.to_html(full_html=False)`）
   - 7セクション構成（SPEC.md準拠）

2. **レポート生成エンジン（`reporter/html.py`）**
   - Parquetからデータ読み込み → 各セクションのHTMLを生成
   - 市場環境サマリー（指標テーブル）
   - セクターヒートマップ（Plotly Treemap → HTML埋め込み）
   - スクリーニング結果テーブル
   - `reports/YYYY-MM-DD.html` に出力

3. **インデックスページ（`reports/index.html`）**
   - 最新レポートへのリダイレクト
   - 過去レポートのアーカイブリンク一覧

4. **日次バッチスクリプト（`scripts/daily_batch.py`）**
   - Phase 1-3の処理を順次実行
   - エラーハンドリング・ログ出力
   - 営業日判定（土日・祝日スキップ）

### 完了条件

```bash
# バッチスクリプトを手動実行
uv run python scripts/daily_batch.py

# 生成されたHTMLを確認
open reports/$(date +%Y-%m-%d).html
# ブラウザでレポートが正しく表示されることを確認
```

## Phase 4: GitHub Actions + GitHub Pages

### タスク

1. **GitHub リポジトリ初期化**
   - `git init` + `.gitignore` 設定
   - GitHubにリモートリポジトリ作成
   - 初回push

2. **GitHub Actions ワークフロー（`.github/workflows/daily_report.yml`）**
   - cron: 毎日 09:00 UTC（18:00 JST）、月〜金
   - `workflow_dispatch` で手動実行も可能
   - uv sync → daily_batch.py 実行 → data/ と reports/ をcommit & push

3. **GitHub Pages 設定**
   - reports/ ディレクトリをGitHub Pagesにデプロイ
   - Actions内でdeploy-pagesアクションを使用

4. **シークレット設定**
   - EDINET_API_KEY（Phase 6で使用、先に設定枠だけ用意）

### 完了条件

```bash
# GitHub Actionsを手動トリガー
gh workflow run daily_report.yml

# 実行完了後、GitHub PagesのURLでレポートが表示されることを確認
# data/ にParquetがcommitされていることを確認
gh run list --workflow=daily_report.yml --limit=1
```

## Phase 5: Streamlitダッシュボード（ローカル深掘り用）

### タスク

1. **ヘッダー（市場指標メトリクス）**
   - st.metric × 4 の横並び表示
   - Parquetから最新値を取得（DuckDB直読み）

2. **概況タブ**
   - 今日のポイント（テキスト表示）
   - セクターヒートマップ（Plotly Treemap）
   - 主要指標スパークライン
   - 値上がり/値下がりランキング

3. **スクリーニングタブ**
   - 3スクリーン + 収束シグナルのサブタブ
   - スクリーニング結果テーブル（スパークライン内蔵）
   - バリュー vs モメンタム散布図（インタラクティブ）

4. **サイドバー（グローバルフィルタ）**
   - 日付選択
   - セクターフィルタ
   - スコア閾値

5. **キャッシュ設定**
   - `@st.cache_data(ttl=3600)` でParquet読み取りをキャッシュ

### 完了条件

```bash
git pull  # 最新データを取得
uv run streamlit run src/stock_report/app.py
# ブラウザで http://localhost:8501 を開いて以下を確認:
# - ヘッダーに主要指数が表示される
# - 概況タブにヒートマップが表示される
# - スクリーニングタブに結果テーブルと散布図が表示される
# - サイドバーのフィルタが機能する
```

## Phase 6: EDINET連携

### タスク

1. **EDINET APIクライアント（`fetcher/fundamental.py`）**
   - EDINET APIキー管理（環境変数）
   - 有価証券報告書の検索・ダウンロード
   - XBRLパース → 標準化された財務指標の抽出
   - `data/fundamentals/latest.parquet` に保存

2. **Piotroski F-Score算出**
   - 9項目の算出ロジック実装
   - 前年比較のためのデータ管理

3. **Magic Formula指標算出**
   - 益利回り（EBIT / EV）
   - 投下資本利益率（EBIT / IC）

4. **Screen Aの完全版への更新**
   - 簡易版（yfinanceのみ）からEDINETデータを使った完全版へ

5. **GitHub Actionsワークフローの更新**
   - EDINET_API_KEYシークレットの設定
   - fundamental取得ステップの追加

### 完了条件

```bash
# EDINET からデータ取得
uv run python -m stock_report.fetcher.fundamental

# F-Score確認
uv run python -c "
import duckdb
print(duckdb.sql(\"SELECT ticker, f_score, earnings_yield, roc FROM 'data/fundamentals/latest.parquet' WHERE f_score IS NOT NULL ORDER BY f_score DESC LIMIT 10\").fetchdf())
"
```

### 注意事項

- EDINET APIキーの取得が必要（無料登録）
- 日本の3月決算企業は4-5月に報告書が集中するため、データ更新頻度は四半期程度
- XBRL解析はedinet-toolsライブラリの機能を最大限活用する

## Phase 7: ウォッチリスト + テーゼチェック + カレンダー

### タスク

1. **ウォッチリストタブ（Streamlit）**
   - config/watchlist.tomlからの銘柄読み込み
   - テーゼチェック表示（変化ありのみ）
   - ウォッチリストテーブル（シグナルバッジ、確信度表示）
   - 個別銘柄詳細Expander（ローソク足 + 出来高 + RSI/MACD）

2. **カレンダータブ（Streamlit）**
   - 決算発表カレンダー
   - 経済指標リリース予定
   - イベント表示

3. **アラート階層**
   - Tier 1: st.error で重要アラート
   - Tier 2: インラインバッジ
   - Tier 3: Expander内

4. **静的HTMLレポートへの反映**
   - ウォッチリストセクション追加
   - カタリストセクション追加
   - テーゼチェックセクション追加

### 完了条件

```bash
# Streamlitで全タブ確認
uv run streamlit run src/stock_report/app.py

# 静的HTMLでも全セクション確認
uv run python scripts/daily_batch.py
open reports/$(date +%Y-%m-%d).html
```
