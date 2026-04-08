"""日次バッチスクリプト

GitHub Actionsおよびローカルから呼び出される。
全パイプライン（データ取得→分析→レポート生成）を順次実行する。
"""

import sys
from datetime import date, timedelta
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

    print(f"{'='*50}")
    print(f"Daily Batch: {target_date}")
    print(f"{'='*50}")

    if not is_business_day(target_date):
        print(f"休日のためスキップ ({target_date})")
        return

    # Step 1: データ取得
    print("\n[1/5] 株価データ取得...")
    from stock_report.fetcher.price import run as fetch_prices
    fetch_prices(days=10)  # 日次実行時は直近10日分を取得（冪等）

    print("\n[2/5] 市場指標取得...")
    from stock_report.fetcher.market import run as fetch_market
    fetch_market(days=10)

    print("\n[3/5] テクニカル指標算出...")
    from stock_report.analyzer.technical import run as run_technical
    run_technical()

    print("\n[4/5] スクリーニング実行...")
    from stock_report.analyzer.screener import run as run_screener
    run_screener(target_date)

    # シグナルライフサイクル更新
    from stock_report.analyzer.signal import run as run_signal
    run_signal(target_date)

    print("\n[5/5] HTMLレポート生成...")
    from stock_report.reporter.html import generate_report
    output_path = generate_report(target_date)

    print(f"\n{'='*50}")
    print(f"完了: {output_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    # 引数で日付指定可能: python daily_batch.py 2026-04-07
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = None
    run_batch(target)
