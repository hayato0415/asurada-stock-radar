from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import update_news_events as legacy  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")
DEFAULT_OUTPUT = ROOT / "docs" / "data" / "news-events.json"


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def title_key(title: str) -> str:
    return re.sub(r"[\W_]+", "", (title or "").lower())


def is_similar_title(title: str, seen: list[str], threshold: float = 0.92) -> bool:
    key = title_key(title)
    if not key:
        return True
    return any(difflib.SequenceMatcher(None, key, old).ratio() >= threshold for old in seen)


def parse_source_datetime(text: str, now: datetime) -> tuple[str, str]:
    """Return source timestamp if the source page exposes one.

    We intentionally return an empty timestamp when the page does not expose a
    recognizable date, instead of pretending the scheduled run time is news time.
    """
    value = normalize_space(text)
    if not value:
        return "", "missing"

    time_match = re.search(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", value)
    hour = int(time_match.group("hour")) if time_match else 0
    minute = int(time_match.group("minute")) if time_match else 0

    patterns = [
        (r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})", "full"),
        (r"(?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?", "month_day"),
    ]
    for pattern, status in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        year = int(match.groupdict().get("year") or now.year)
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            dt = datetime(year, month, day, hour, minute, tzinfo=TAIPEI_TZ)
        except ValueError:
            continue
        return dt.strftime("%Y-%m-%d %H:%M"), status

    if "今天" in value and time_match:
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.strftime("%Y-%m-%d %H:%M"), "today_time"

    if time_match:
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.strftime("%Y-%m-%d %H:%M"), "time_only"

    return "", "missing"


def anchor_context(anchor) -> str:
    chunks = [anchor.get_text(" ", strip=True)]
    node = anchor
    for _ in range(3):
        node = node.parent
        if not node:
            break
        chunks.append(node.get_text(" ", strip=True))
    return normalize_space(" ".join(chunks))


def extract_items(source: legacy.NewsSource, html: str, current: datetime) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    for anchor in soup.find_all("a", href=True):
        title = normalize_space(anchor.get_text(" ", strip=True))
        url = urljoin(source.url, anchor["href"])
        if not title or len(title) < 8 or not legacy.is_real_url(url):
            continue
        if url in seen_urls or is_similar_title(title, seen_titles):
            continue
        context = anchor_context(anchor)
        published_at, date_status = parse_source_datetime(context, current)
        seen_urls.add(url)
        seen_titles.append(title_key(title))
        items.append({
            "title": title,
            "url": url,
            "published_at": published_at,
            "date_status": date_status,
            "context": context,
        })
    return items


def fetch_source_html(source: legacy.NewsSource, warnings: list[str]) -> str:
    try:
        return legacy.fetch_html(source)
    except requests.exceptions.SSLError:
        warnings.append(f"{source.name}: SSL 驗證失敗，已使用 verify=False 重試")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AsuradaRadar/1.0",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        }
        response = requests.get(source.url, headers=headers, timeout=25, verify=False)
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text


def build_events(limit: int, output: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    current = now_taipei()
    stocks = legacy.load_stocks()
    events: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    source_success = 0

    previous_urls: set[str] = set()
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            previous_items = previous.get("items", previous) if isinstance(previous, dict) else previous
            if isinstance(previous_items, list):
                previous_urls = {str(item.get("source_url") or item.get("url") or "") for item in previous_items if isinstance(item, dict)}
        except Exception as exc:
            warnings.append(f"舊新聞檔讀取失敗：{exc}")

    for source in legacy.SOURCES:
        try:
            html = fetch_source_html(source, warnings)
            links = extract_items(source, html, current)
            source_success += 1
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")
            continue

        for item in links:
            title = item["title"]
            url = item["url"]
            if url in seen_urls or is_similar_title(title, seen_titles):
                continue
            category = legacy.infer_category(title)
            if not category:
                continue
            related_stocks = legacy.related_stocks_for(category, title, stocks)
            if not related_stocks:
                continue
            keywords = legacy.related_keywords_for(category)
            seen_urls.add(url)
            seen_titles.append(title_key(title))
            events.append({
                "date": item["published_at"],
                "title": title,
                "source_name": source.name,
                "source_url": url,
                "url": url,
                "category": category,
                "market_group": legacy.infer_market_group(title, category, keywords),
                "news_region": legacy.infer_news_region(source.region),
                "related_keywords": keywords,
                "related_stocks": related_stocks,
                "summary": legacy.make_summary(title, category, source.name),
                "asurada_analysis": legacy.make_analysis(title, category, related_stocks),
                "event_strength": legacy.infer_strength(title),
                "impact": legacy.infer_impact(title),
                "date_status": item["date_status"],
            })
            if len(events) >= limit:
                break
        if len(events) >= limit:
            break

    new_urls = {str(item.get("source_url") or item.get("url") or "") for item in events}
    new_items_count = len([url for url in new_urls if url and url not in previous_urls])
    dated = sorted([str(item.get("date") or "") for item in events if item.get("date")], reverse=True)
    report = {
        "success": bool(events),
        "generated_at": current.strftime("%Y-%m-%d %H:%M:%S Asia/Taipei"),
        "events_count": len(events),
        "new_items_count": new_items_count,
        "content_latest_at": dated[0] if dated else "",
        "sources_attempted": len(legacy.SOURCES),
        "sources_success": source_success,
        "errors": errors,
        "warnings": warnings,
        "output": str(output.relative_to(ROOT)).replace("\\", "/"),
    }
    return events, report


def write_events(events: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        legacy.write_theme_candidates(events)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch latest source-linked market news for GitHub Pages.")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--min-events", type=int, default=5)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output

    events, report = build_events(limit=max(args.limit, 1), output=output)
    if len(events) < args.min_events:
        report["success"] = False
        report["errors"].append(f"抓到 {len(events)} 則新聞，低於最低門檻 {args.min_events}，未覆蓋既有 news-events.json。")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    write_events(events, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
