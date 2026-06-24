from __future__ import annotations

import argparse
import json

from data_sources import DataProvider
from reporting import write_home_dashboard_data, write_reports
from scoring_model import build_candidates, prefilter_by_revenue, top_report
from update_news_events import NEWS_OUTPUT_PATH, build_events, write_events


def run_scan(
    refresh: bool = False,
    price_limit: int = 180,
    top_n: int = 30,
    site_top_n: int = 180,
) -> dict[str, object]:
    provider = DataProvider()
    stocks = provider.load_or_fetch_stock_list(refresh=refresh)
    revenue = provider.load_or_fetch_revenue(refresh=refresh)
    manual = provider.load_manual_factors()
    prefiltered = prefilter_by_revenue(revenue, limit=price_limit)
    price_signals = provider.fetch_price_signals(prefiltered, limit=price_limit)
    candidates = build_candidates(stocks, revenue, manual, price_signals)
    report = top_report(candidates, limit=top_n)
    interactive_report = top_report(candidates, limit=max(site_top_n, top_n))
    csv_path, html_path = write_reports(report, interactive_report=interactive_report)
    try:
        events = build_events()
        existing_news_count = 0
        if NEWS_OUTPUT_PATH.exists():
            try:
                existing_news_count = len(json.loads(NEWS_OUTPUT_PATH.read_text(encoding="utf-8")))
            except Exception:
                existing_news_count = 0
        should_replace_news = len(events) >= 5 and (
            existing_news_count == 0 or len(events) >= min(10, existing_news_count)
        )
        if should_replace_news:
            write_events(events)
            news_count: int | str = len(events)
        else:
            news_count = f"{len(events)}（保留既有新聞資料）"
    except Exception as exc:
        news_count = f"新聞更新失敗：{exc}"
    try:
        home_dashboard_files = [str(path) for path in write_home_dashboard_data()]
    except Exception as exc:
        home_dashboard_files = [f"首頁戰情資料更新失敗：{exc}"]
    return {
        "股票清單檔": str(provider.data_dir / "tw_stock_list.csv"),
        "候選股數": len(candidates),
        "輸出前N名": len(report),
        "新聞事件數": news_count,
        "首頁戰情資料": home_dashboard_files,
        "網站互動資料筆數": len(interactive_report),
        "CSV": str(csv_path),
        "HTML": str(html_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="阿斯拉台股主升段雷達每日掃描")
    parser.add_argument("--refresh", action="store_true", help="重新下載官方清單與月營收")
    parser.add_argument("--price-limit", type=int, default=180, help="抓取股價量能的預篩股票數")
    parser.add_argument("--top-n", type=int, default=30, help="報告輸出候選股數")
    parser.add_argument("--site-top-n", type=int, default=180, help="網站互動雷達資料筆數")
    args = parser.parse_args()
    result = run_scan(
        refresh=args.refresh,
        price_limit=args.price_limit,
        top_n=args.top_n,
        site_top_n=args.site_top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
