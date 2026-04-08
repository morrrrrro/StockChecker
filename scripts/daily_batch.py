"""日次バッチスクリプト

GitHub Actionsおよびローカルから呼び出される。
全パイプライン（データ取得→分析→レポート生成）を順次実行する。

ファンダメンタルデータは週1回（月曜）のみ取得する（大量銘柄で時間がかかるため）。
"""

import sys
from datetime import date
from pathlib import Path

# プロジェクトルートをパスに追加（直接実行時用）
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


def is_business_day(d: date) -> bool:
    """営業日判定（土日のみ。祝日は将来対応）"""
    return d.weekday() < 5


def run_batch(target_date: date | None = None) -> None:
    """日次バッチ処理を実行する"""
    if target_date is None:
        target_date = date.today()

    print(f"{'='*60}")
    print(f"Daily Batch: {target_date}")
    print(f"{'='*60}")

    if not is_business_day(target_date):
        print(f"休日のためスキップ ({target_date})")
        return

    # Step 1: JPX銘柄リスト更新（週1回）
    if target_date.weekday() == 0:  # 月曜日
        print("\n[0/6] JPX銘柄リスト更新...")
        from stock_report.universe import fetch_tse_list
        fetch_tse_list(force_refresh=True)

    # Step 2: 株価データ取得（全ユニバース）
    print("\n[1/6] 株価データ取得...")
    from stock_report.fetcher.price import run as fetch_prices
    fetch_prices(days=10)  # 日次実行時は直近10日分を取得（冪等）

    # Step 3: 市場指標取得
    print("\n[2/6] 市場指標取得...")
    from stock_report.fetcher.market import run as fetch_market
    fetch_market(days=10)

    # Step 4: ファンダメンタルデータ取得（週1回 or 初回 or 差分のみ）
    from pathlib import Path
    fundamentals_path = Path("data/fundamentals/latest.parquet")
    needs_fundamental = target_date.weekday() == 0  # 月曜日
    if fundamentals_path.exists():
        import pandas as pd
        existing_count = len(pd.read_parquet(fundamentals_path))
        # 銘柄数が少なすぎる場合も取得（ユニバース拡大後の初回対応）
        if existing_count < 500:
            needs_fundamental = True

    if needs_fundamental:
        print("\n[3/6] ファンダメンタルデータ取得...")
        from stock_report.fetcher.fundamental import run as fetch_fundamental
        fetch_fundamental(incremental=True)
    else:
        print(f"\n[3/6] ファンダメンタルデータ取得... スキップ（次回: 月曜）")

    # Step 5: テクニカル指標算出
    print("\n[4/6] テクニカル指標算出...")
    from stock_report.analyzer.technical import run as run_technical
    run_technical()

    # Step 6: スクリーニング実行
    print("\n[5/6] スクリーニング実行...")
    from stock_report.analyzer.screener import run as run_screener
    run_screener(target_date)

    # シグナルライフサイクル更新
    from stock_report.analyzer.signal import run as run_signal
    run_signal(target_date)

    # Step 7: HTMLレポート生成
    print("\n[6/6] HTMLレポート生成...")
    from stock_report.reporter.html import generate_report
    output_path = generate_report(target_date)

    print(f"\n{'='*60}")
    print(f"完了: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    # 引数で日付指定可能: python daily_batch.py 2026-04-07
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = None
    run_batch(target)
