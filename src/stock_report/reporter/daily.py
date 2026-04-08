"""日次レポートデータ組み立て

各モジュールの出力を集約し、レポート生成に渡す。
"""

from datetime import date

from stock_report.reporter.html import generate_report


def run(report_date: date | None = None) -> None:
    """日次レポートを生成する"""
    generate_report(report_date)


if __name__ == "__main__":
    run()
