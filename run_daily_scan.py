from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data_sources import DataProvider
from reporting import write_home_dashboard_data, write_reports
from scoring_model import build_candidates, prefilter_by_revenue, top_report
from update_news_events import NEWS_OUTPUT_PATH, build_events, write_events

ROOT = Path(__file__).resolve().parent
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def run_helper_script(script_name: str) -> dict[str, object]:
    script_path = ROOT / "scripts" / script_name
    if not script_path.exists():
        return {
            "script": script_name,
            "success": False,
            "skipped": True,
            "message": "script not found",
        }
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "script": script_name,
        "success": completed.returncode == 0,
        "skipped": False,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[-2000:],
        "stderr": completed.stderr.strip()[-2000:],
    }


def write_update_report(payload: dict[str, object]) -> list[str]:
    updated_at = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S Asia/Taipei")
    report = {
        "updated_at": updated_at,
        "success": True,
        "schedule_policy": "daily; no trading-day skip",
        "pages_data_scope": [
            "首頁儀表板",
            "AI選股清單",
            "產業題材庫",
            "重大新聞",
            "個股概覽",
            "持股追蹤資料參照",
        ],
        **payload,
    }
    outputs: list[str] = []
    for folder in (ROOT / "data", ROOT / "docs" / "data"):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "update_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outputs.append(str(path))
    return outputs


def run_scan(
    refresh: bool = False,
    price_limit: int = 180,
    top_n: int = 30,
    site_top_n: int = 180,
) -> dict[str, object]:
    pre_update_results = [
        run_helper_script("update_stock_master.py"),
    ]
    provider = DataProvider()
    stocks = provider.load_or_fetch_stock_list(refresh=refresh)
    revenue = provider.load_or_fetch_revenue(refresh=refresh)
    manual = provider.load_manual_factors()
    prefiltered = prefilter_by_revenue(revenue, limit=price_limit)
    price_signals = provider.fetch_price_signals(prefiltered, limit=price_limit)
    candidates = build_candidates(stocks, revenue, manual, price_signals)
    report = top_report(candidates, limit=top_n)
    interactive_report = top_report(candidates, limit=max(site_top_n, top_n), include_price_gaps=True)
    csv_path, html_path = write_reports(report, interactive_report=interactive_report)
    if "price_source_status" in candidates:
        price_status = candidates["price_source_status"]
    elif "股價資料來源" in candidates:
        price_status = candidates["股價資料來源"].astype(str).str.contains("fallback", case=False, na=False).map(
            {True: "fallback", False: "missing"}
        )
    else:
        price_status = candidates.assign(price_source_status="missing")["price_source_status"]
    price_status = price_status.fillna("missing").astype(str).str.lower()
    official_eligible = (
        candidates["official_rank_eligible"]
        if "official_rank_eligible" in candidates
        else candidates.assign(official_rank_eligible=False)["official_rank_eligible"]
    )
    price_qa = {
        "total_stocks_scanned": int(len(candidates)),
        "verified_price_count": int(price_status.eq("verified").sum()),
        "fallback_price_count": int(price_status.eq("fallback").sum()),
        "missing_price_count": int(price_status.eq("missing").sum()),
        "excluded_due_to_fallback_price_count": int(
            (price_status.eq("fallback") & ~official_eligible.fillna(False).astype(bool)).sum()
        ),
    }
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
    post_update_results = [
        run_helper_script("build_source_catalog.py"),
        run_helper_script("build_concepts_taxonomy.py"),
        run_helper_script("build_radar_rankings.py"),
    ]
    result = {
        "股票清單檔": str(provider.data_dir / "tw_stock_list.csv"),
        "候選股數": len(candidates),
        "輸出前N名": len(report),
        "新聞事件數": news_count,
        "首頁戰情資料": home_dashboard_files,
        "網站互動資料筆數": len(interactive_report),
        "price_data_qa": price_qa,
        "pre_update_scripts": pre_update_results,
        "post_update_scripts": post_update_results,
        "CSV": str(csv_path),
        "HTML": str(html_path),
    }
    result["update_report_files"] = write_update_report(result)
    return result


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
