"""Streamlit Cloud エントリポイント"""

import sys
from pathlib import Path

# srcをパスに追加（Streamlit Cloud用）
sys.path.insert(0, str(Path(__file__).parent / "src"))

from stock_report.app import main

main()
