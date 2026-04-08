"""銘柄ユニバース管理

全東証銘柄（JPX公式リスト）+ 米国主要株 + ETF/指数 + 為替・商品を管理する。
"""

from pathlib import Path

import pandas as pd

from stock_report.db import DATA_DIR

CACHE_DIR = DATA_DIR / "universe"
TSE_CACHE = CACHE_DIR / "tse_list.parquet"
JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

# 米国主要株（S&P100ベース + 人気銘柄）
US_STOCKS = [
    # GAFAM+
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # 半導体
    "TSM", "AVGO", "AMD", "INTC", "QCOM", "ASML", "MU",
    # 金融
    "JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B",
    # ヘルスケア
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO",
    # 消費財
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE",
    # エネルギー
    "XOM", "CVX", "COP",
    # 通信
    "DIS", "NFLX", "CMCSA", "T", "VZ",
    # 工業
    "CAT", "BA", "HON", "GE", "MMM", "UPS",
    # その他注目
    "CRM", "ORCL", "ADBE", "NOW", "UBER", "COIN", "PLTR",
    "SQ", "SHOP", "ZM", "CRWD", "SNOW", "DDOG",
]

# 主要ETF
ETFS = [
    # 米国ETF
    "SPY",   # S&P 500
    "QQQ",   # NASDAQ 100
    "DIA",   # Dow Jones
    "IWM",   # Russell 2000
    "VTI",   # Total Stock Market
    "VOO",   # S&P 500 (Vanguard)
    "EEM",   # Emerging Markets
    "VWO",   # Emerging Markets (Vanguard)
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Oil
    "TLT",   # 20+ Year Treasury Bond
    "HYG",   # High Yield Corporate Bond
    "LQD",   # Investment Grade Corporate Bond
    "VNQ",   # Real Estate
    # 日本ETF
    "1306.T",  # TOPIX連動
    "1321.T",  # 日経225連動
    "1570.T",  # 日経レバレッジ
    "1357.T",  # 日経ダブルインバース
    "2558.T",  # S&P500連動（国内ETF）
    "1343.T",  # REIT指数連動
    "1540.T",  # 純金上場信託
    "1699.T",  # 原油先物連動
]

# 為替・債券・商品・指数
MARKET_INDICATORS = {
    # 主要指数
    "nikkei225": "^N225",
    "topix": "^TPX",
    "sp500": "^GSPC",
    "dow": "^DJI",
    "nasdaq": "^IXIC",
    "russell2000": "^RUT",
    "ftse100": "^FTSE",
    "dax": "^GDAXI",
    "hang_seng": "^HSI",
    "shanghai": "000001.SS",
    # 為替
    "usdjpy": "JPY=X",
    "eurjpy": "EURJPY=X",
    "eurusd": "EURUSD=X",
    "gbpjpy": "GBPJPY=X",
    # 債券利回り
    "us10y": "^TNX",
    "us2y": "^IRX",
    "jp10y": "^TNX",  # 日本10年債はyfinanceで直接取得困難、代替
    # ボラティリティ
    "vix": "^VIX",
    # 商品
    "wti_oil": "CL=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
    "natural_gas": "NG=F",
    # 暗号資産
    "btcusd": "BTC-USD",
    "ethusd": "ETH-USD",
}


def fetch_tse_list(force_refresh: bool = False) -> pd.DataFrame:
    """JPX公式リストから全東証銘柄を取得する（キャッシュあり）"""
    if not force_refresh and TSE_CACHE.exists():
        return pd.read_parquet(TSE_CACHE)

    print("JPX銘柄リスト取得中...")
    raw = pd.read_excel(JPX_URL)

    df = pd.DataFrame({
        "code": raw["コード"].astype(str),
        "name": raw["銘柄名"],
        "market": raw["市場・商品区分"],
        "sector_33": raw["33業種区分"],
        "sector_17": raw["17業種区分"],
        "scale": raw["規模区分"],
    })

    # yfinanceティッカーを生成
    df["ticker"] = df["code"] + ".T"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(TSE_CACHE, index=False)
    print(f"  {len(df)}銘柄をキャッシュ保存")
    return df


def get_tse_stocks(include_etf: bool = False) -> list[str]:
    """東証の株式銘柄ティッカーを返す"""
    df = fetch_tse_list()

    if include_etf:
        return df["ticker"].tolist()

    # 内国株式のみ（ETF/ETN/REIT等を除外）
    stock_markets = df["market"].str.contains("内国株式", na=False)
    return df[stock_markets]["ticker"].tolist()


def get_us_stocks() -> list[str]:
    """米国主要株のティッカーを返す"""
    return US_STOCKS.copy()


def get_etfs() -> list[str]:
    """主要ETFのティッカーを返す"""
    return ETFS.copy()


def get_market_indicators() -> dict[str, str]:
    """市場指標のティッカーマッピングを返す"""
    return MARKET_INDICATORS.copy()


def get_all_tickers() -> dict[str, list[str]]:
    """全カテゴリのティッカーをまとめて返す"""
    tse = get_tse_stocks()
    us = get_us_stocks()
    etfs = get_etfs()

    print(f"ユニバース: TSE {len(tse)} + US {len(us)} + ETF {len(etfs)} = {len(tse) + len(us) + len(etfs)}銘柄")
    return {
        "tse": tse,
        "us": us,
        "etf": etfs,
    }


def get_tse_sector_map() -> dict[str, str]:
    """東証銘柄のセクターマッピングを返す（ticker → sector_33）"""
    df = fetch_tse_list()
    return dict(zip(df["ticker"], df["sector_33"]))


# 米国株の企業名マッピング
US_STOCK_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "META": "Meta", "NVDA": "NVIDIA", "TSLA": "Tesla", "TSM": "TSMC",
    "AVGO": "Broadcom", "AMD": "AMD", "INTC": "Intel", "QCOM": "Qualcomm",
    "ASML": "ASML", "MU": "Micron", "JPM": "JPMorgan", "BAC": "Bank of America",
    "GS": "Goldman Sachs", "MS": "Morgan Stanley", "V": "Visa", "MA": "Mastercard",
    "BRK-B": "Berkshire", "JNJ": "J&J", "UNH": "UnitedHealth", "PFE": "Pfizer",
    "ABBV": "AbbVie", "MRK": "Merck", "LLY": "Eli Lilly", "TMO": "Thermo Fisher",
    "WMT": "Walmart", "PG": "P&G", "KO": "Coca-Cola", "PEP": "PepsiCo",
    "COST": "Costco", "MCD": "McDonald's", "NKE": "Nike", "XOM": "Exxon",
    "CVX": "Chevron", "COP": "ConocoPhillips", "DIS": "Disney", "NFLX": "Netflix",
    "CMCSA": "Comcast", "T": "AT&T", "VZ": "Verizon", "CAT": "Caterpillar",
    "BA": "Boeing", "HON": "Honeywell", "GE": "GE", "MMM": "3M", "UPS": "UPS",
    "CRM": "Salesforce", "ORCL": "Oracle", "ADBE": "Adobe", "NOW": "ServiceNow",
    "UBER": "Uber", "COIN": "Coinbase", "PLTR": "Palantir", "SQ": "Block",
    "SHOP": "Shopify", "ZM": "Zoom", "CRWD": "CrowdStrike", "SNOW": "Snowflake",
    "DDOG": "Datadog",
}


def get_name_map() -> dict[str, str]:
    """全銘柄の ticker → 企業名 マッピングを返す"""
    name_map = {}

    # 東証銘柄
    df = fetch_tse_list()
    for _, row in df.iterrows():
        name_map[row["ticker"]] = row["name"]

    # 米国株
    name_map.update(US_STOCK_NAMES)

    return name_map


if __name__ == "__main__":
    # キャッシュ強制更新
    df = fetch_tse_list(force_refresh=True)
    print(f"\n全銘柄数: {len(df)}")

    # 市場区分別の内訳
    print("\n市場区分別:")
    print(df["market"].value_counts().to_string())

    tickers = get_all_tickers()
    for category, lst in tickers.items():
        print(f"\n{category}: {len(lst)}銘柄")
