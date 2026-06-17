from __future__ import annotations

import argparse
import json

from data_sources import DataProvider
from reporting import write_reports
from scoring_model import build_candidates, prefilter_by_revenue, top_report


def run_scan(refresh: bool = False, price_limit: int = 180, top_n: int = 30) -> dict[str, object]:
    provider = DataProvider()
    stocks = provider.load_or_fetch_stock_list(refresh=refresh)
    revenue = provider.load_or_fetch_revenue(refresh=refresh)
    manual = provider.load_manual_factors()
    prefiltered = prefilter_by_revenue(revenue, limit=price_limit)
    price_signals = provider.fetch_price_signals(prefiltered, limit=price_limit)
    candidates = build_candidates(stocks, revenue, manual, price_signals)
    report = top_report(candidates, limit=top_n)
    csv_path, html_path = write_reports(report)
    return {
        "股票清單檔": str(provider.data_dir / "tw_stock_list.csv"),
        "候選股數": len(candidates),
        "輸出前N名": len(report),
        "CSV": str(csv_path),
        "HTML": str(html_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="阿斯拉台股主升段雷達每日掃描")
    parser.add_argument("--refresh", action="store_true", help="重新下載官方清單與月營收")
    parser.add_argument("--price-limit", type=int, default=180, help="抓取股價量能的預篩股票數")
    parser.add_argument("--top-n", type=int, default=30, help="報告輸出候選股數")
    args = parser.parse_args()
    result = run_scan(refresh=args.refresh, price_limit=args.price_limit, top_n=args.top_n)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

