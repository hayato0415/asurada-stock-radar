from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = DOCS / "data"
TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")

REQUIRED_HTML = ["index.html", "radar.html", "news.html", "concepts.html"]
REQUIRED_JSON = [
    "daily_market_snapshot.json",
    "daily_hot_stocks.json",
    "daily_hot_themes.json",
    "market-latest.json",
    "radar-latest.json",
    "news-latest.json",
    "concepts-moneydj.json",
    "update-log.json",
    "site-version.json",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def items_from(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("items"), list):
            return raw["items"]
        if isinstance(raw.get("concepts"), list):
            return raw["concepts"]
    return []


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("T", " ").replace("+08:00", "").replace("+00:00", "").replace("Asia/Taipei", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).replace(tzinfo=TAIPEI_TZ)
        except ValueError:
            continue
    return None


def fail(errors: list[str]) -> None:
    if errors:
        print("Site build validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []

    for name in REQUIRED_HTML:
        if not (DOCS / name).exists():
            errors.append(f"missing docs/{name}")

    for name in REQUIRED_JSON:
        if not (DATA / name).exists():
            errors.append(f"missing docs/data/{name}")
    fail(errors)

    site_version = read_json(DATA / "site-version.json")
    expected_build_id = site_version.get("build_id")
    if not expected_build_id:
        errors.append("site-version.json missing build_id")

    for name in REQUIRED_JSON:
        data = read_json(DATA / name)
        build_id = data.get("build_id") if isinstance(data, dict) else ""
        if build_id != expected_build_id:
            errors.append(f"{name} build_id mismatch: {build_id!r} != {expected_build_id!r}")

    radar = read_json(DATA / "radar-latest.json")
    if len(items_from(radar)) <= 0:
        errors.append("radar-latest.json has no items")

    concepts = read_json(DATA / "concepts-moneydj.json")
    if len(items_from(concepts)) <= 0:
        errors.append("concepts-moneydj.json has no concepts")

    news = read_json(DATA / "news-latest.json")
    news_items = items_from(news)
    if not news_items:
        errors.append("news-latest.json has no items")
    if news.get("stale") is not True:
        updated = parse_datetime(news.get("updated_at"))
        latest = parse_datetime(news.get("content_latest_at"))
        if updated and latest and updated - latest > timedelta(hours=12):
            errors.append("news-latest.json content is older than 12 hours but stale is not true")

    invalid_sources = []
    for item in news_items[:80]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url") or item.get("url") or "").strip()
        if not url:
            warnings.append(f"news item missing source_url: {item.get('title', '')[:60]}")
            continue
        if re.search(r"(example\.com|localhost|127\.0\.0\.1)", url, re.I):
            invalid_sources.append(url)
    if invalid_sources:
        errors.append(f"news-latest.json contains invalid source URLs: {invalid_sources[:3]}")

    fail(errors)
    for warning in warnings[:10]:
        print(f"[warn] {warning}")
    print(f"Site build validation ok: {expected_build_id}")


if __name__ == "__main__":
    main()
