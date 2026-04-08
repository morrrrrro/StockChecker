"""DuckDBクエリエンジン + Parquet I/Oヘルパー"""

from pathlib import Path

import duckdb
import pandas as pd

# プロジェクトルートからの相対パス解決
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def query(sql: str) -> pd.DataFrame:
    """DuckDBインメモリ接続でSQLを実行し、DataFrameを返す"""
    return duckdb.sql(sql).fetchdf()


def query_scalar(sql: str):
    """単一値を返すクエリ用"""
    return duckdb.sql(sql).fetchone()[0]


def save_parquet(df: pd.DataFrame, path: str | Path) -> None:
    """DataFrameをParquetファイルに保存する"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def append_to_monthly_parquet(df: pd.DataFrame, base_dir: str | Path, date_col: str = "date") -> None:
    """月別Parquetファイルにデータを追記する

    同一日のデータは上書きされる（冪等性）。
    dfのdate_colから月を判定し、YYYY-MM.parquet に振り分ける。
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    df[date_col] = pd.to_datetime(df[date_col])

    # 月ごとにグループ化
    df["_month"] = df[date_col].dt.to_period("M").astype(str)
    for month, group in df.groupby("_month"):
        parquet_path = base_dir / f"{month}.parquet"
        group = group.drop(columns=["_month"])

        if parquet_path.exists():
            # 既存データを読み込み、同一日のデータを除外してからmerge
            existing = pd.read_parquet(parquet_path)
            new_dates = set(group[date_col].dt.date)
            existing = existing[~pd.to_datetime(existing[date_col]).dt.date.isin(new_dates)]
            merged = pd.concat([existing, group], ignore_index=True)
            merged = merged.sort_values(date_col).reset_index(drop=True)
            save_parquet(merged, parquet_path)
        else:
            save_parquet(group, parquet_path)
