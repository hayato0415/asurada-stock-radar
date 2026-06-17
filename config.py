from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SITE_DIR = BASE_DIR / "docs"

STOCK_LIST_PATH = DATA_DIR / "tw_stock_list.csv"
REVENUE_PATH = DATA_DIR / "monthly_revenue_latest.csv"
MANUAL_FACTORS_PATH = DATA_DIR / "manual_factors.csv"

REPORT_COLUMNS = [
    "股票代號",
    "股票名稱",
    "概念股",
    "公司業務",
    "關注原因",
    "月營收年增率",
    "月營收月增率",
    "EPS 是否轉虧為盈",
    "毛利率是否改善",
    "法人是否上修目標價",
    "股價是否仍在低位階",
    "成交量是否溫和放大",
    "阿斯拉評級",
    "風險說明",
    "是否適合慢慢買",
]
