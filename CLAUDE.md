# CLAUDE.md

## プロジェクト概要

東証上場銘柄を対象とした株価日次レポートアプリ。
GitHub Actionsで日次バッチ実行 → Parquetにデータ蓄積 → 静的HTMLレポート生成 → GitHub Pagesで公開。
ローカルではStreamlitで深掘り分析が可能。

## 技術スタック

- Python 3.13.3（pyenv）
- uv（依存管理）
- DuckDB（クエリエンジン、Parquet直読み）
- Parquet（データ保存、gitで管理）
- Plotly + Jinja2（静的HTMLレポート生成）
- Streamlit + Plotly（ローカルダッシュボード）
- yfinance / EDINET API（データ取得）
- pandas-ta（テクニカル分析）
- GitHub Actions（日次バッチ）
- GitHub Pages（レポート公開）

## コマンド

```bash
# 依存インストール
uv sync

# データ取得（手動実行）
uv run python -m stock_report.fetcher.price
uv run python -m stock_report.fetcher.market

# 分析実行
uv run python -m stock_report.analyzer.screener

# 日次バッチ（全処理を順次実行、GitHub Actionsでも同じものが走る）
uv run python scripts/daily_batch.py

# ローカルダッシュボード起動
uv run streamlit run src/stock_report/app.py
```

## ディレクトリ構成

- `src/stock_report/fetcher/` — データ取得（yfinance, EDINET）
- `src/stock_report/analyzer/` — テクニカル分析、スクリーニング、スコアリング
- `src/stock_report/reporter/` — レポートデータ生成、静的HTML生成
- `src/stock_report/db.py` — DuckDBクエリエンジン（Parquet直読み）
- `src/stock_report/app.py` — Streamlitダッシュボード
- `templates/report.html` — Jinja2テンプレート（GitHub Pages用）
- `data/` — Parquetデータ（gitで管理・蓄積）
- `reports/` — 生成された静的HTML（GitHub Pagesにデプロイ）
- `config/watchlist.toml` — 監視銘柄定義

## コーディングルール

- 各モジュールは `python -m stock_report.module_name` で独立実行可能にする
- DuckDBは永続ファイルを持たない（Parquetを直読みするクエリエンジンとして使う）
- 同一日のデータは上書き保存（冪等性を担保）
- 日本語コメントで概要を書く
- 型ヒントを付ける
