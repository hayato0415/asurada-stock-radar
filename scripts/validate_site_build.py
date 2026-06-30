#!/usr/bin/env python3
"""Validate GitHub Pages build data consistency."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = DOCS / "data"
try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")

REQUIRED_HTML = [
    "index.html",
    "radar.html",
    "concepts.html",
    "news.html",
    "stock.html",
    "portfolio.html",
]

REQUIRED_JSON = [
    "site-version.json",
    "update-log.json",
    "market-latest.json",
    "radar-latest.json",
    "news-latest.json",
    "concepts-moneydj.json",
]

FRESHNESS_THRESHOLDS = {
    "news-latest.json": timedelta(hours=12),
    "market-latest.json": timedelta(days=4),
    "radar-latest.json": timedelta(days=4),
    "daily_market_snapshot.json": timedelta(days=4),
    "daily_hot_stocks.json": timedelta(days=4),
    "daily_hot_themes.json": timedelta(days=4),
    "concepts-moneydj.json": timedelta(days=14),
}


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "資料待補", "未標示"}:
        return None
    normalized = text.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TAIPEI)
        return parsed.astimezone(TAIPEI)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y-%m",
    ):
        try:
            parsed = datetime.strptime(normalized[: len(datetime.now().strftime(fmt))], fmt)
            if fmt == "%Y-%m":
                parsed = parsed.replace(day=1)
            return parsed.replace(tzinfo=TAIPEI)
        except ValueError:
            continue
    return None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def item_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    if isinstance(payload.get("items"), list):
        return len(payload["items"])
    if isinstance(payload.get("concepts"), list):
        return len(payload["concepts"])
    return 0


def collect_content_dates(filename: str, payload: Any) -> list[datetime]:
    values: list[datetime] = []

    def add(value: Any) -> None:
        parsed = parse_datetime(value)
        if parsed:
            values.append(parsed)

    if not isinstance(payload, dict):
        return values
    items = payload.get("items")
    if not isinstance(items, list):
        concepts = payload.get("concepts")
        items = concepts if isinstance(concepts, list) else []

    if filename == "market-latest.json":
        snapshot = payload.get("snapshot")
        if isinstance(snapshot, dict):
            add(snapshot.get("market_date"))
            add(snapshot.get("date"))
        add(payload.get("content_latest_at"))
        add(payload.get("market_date"))
        add(payload.get("date"))
    elif filename == "daily_market_snapshot.json":
        add(payload.get("market_date"))
        add(payload.get("date"))
    elif filename == "radar-latest.json":
        for item in items:
            if isinstance(item, dict):
                for key in ("market_date", "quote_date", "date", "updated_at"):
                    add(item.get(key))
        add(payload.get("content_latest_at"))
        add(payload.get("market_date"))
        add(payload.get("date"))
    elif filename == "news-latest.json":
        for item in items:
            if isinstance(item, dict):
                for key in ("date", "published_at", "published_time", "time", "updated_at"):
                    add(item.get(key))
        add(payload.get("content_latest_at"))
    elif filename == "concepts-moneydj.json":
        add(payload.get("content_latest_at"))
        add(payload.get("generated_at"))
        add(payload.get("updated_at"))
    else:
        for item in items:
            if isinstance(item, dict):
                for key in ("market_date", "date", "updated_at", "generated_at"):
                    add(item.get(key))
        add(payload.get("content_latest_at"))
        add(payload.get("date"))
    return values


def validate_urls(news: dict[str, Any], errors: list[str]) -> None:
    for item in news.get("items", []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url") or item.get("url") or "").strip()
        if not url:
            continue
        lowered = url.lower()
        if "example.com" in lowered or "localhost" in lowered:
            errors.append(f"news-latest.json contains invalid source_url: {url}")


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []

    for filename in REQUIRED_HTML:
        if not (DOCS / filename).exists():
            errors.append(f"missing docs/{filename}")

    for filename in REQUIRED_JSON:
        if not (DATA / filename).exists():
            errors.append(f"missing docs/data/{filename}")

    if errors:
        print("\n".join(errors))
        raise SystemExit(1)

    site_version = read_json(DATA / "site-version.json")
    build_id = site_version.get("build_id")
    if not build_id:
        errors.append("site-version.json missing build_id")

    site_dataset_map = {
        item.get("file"): item for item in site_version.get("datasets", []) if isinstance(item, dict)
    }

    for filename in REQUIRED_JSON:
        payload = read_json(DATA / filename)
        if filename not in {"site-version.json", "update-log.json"}:
            if payload.get("build_id") != build_id:
                errors.append(f"{filename} build_id mismatch")

        if filename == "radar-latest.json" and item_count(payload) == 0:
            errors.append("radar-latest.json has no items")
        if filename == "news-latest.json" and item_count(payload) == 0:
            errors.append("news-latest.json has no items")
        if filename == "concepts-moneydj.json" and item_count(payload) == 0:
            errors.append("concepts-moneydj.json has no concepts")

        if filename in {"site-version.json", "update-log.json"}:
            continue

        updated = parse_datetime(payload.get("updated_at"))
        dates = collect_content_dates(filename, payload)
        content_latest = max(dates) if dates else parse_datetime(payload.get("content_latest_at"))
        stale = bool(payload.get("stale"))

        summary = site_dataset_map.get(filename)
        if summary:
            summary_stale = bool(summary.get("stale")) or summary.get("status") == "stale"
            if summary_stale != stale:
                errors.append(f"{filename} stale flag differs between data and site-version")

        if not content_latest:
            if not stale:
                errors.append(f"{filename} has no content_latest_at but stale=false")
            continue

        if updated:
            threshold = FRESHNESS_THRESHOLDS.get(filename)
            if threshold and updated - content_latest > threshold and not stale:
                errors.append(
                    f"{filename} updated_at is new but content_latest_at is old "
                    f"({content_latest.isoformat()}); stale must be true"
                )

        if stale:
            warnings.append(f"{filename} is stale: {payload.get('stale_reason', '')}")

    news = read_json(DATA / "news-latest.json")
    validate_urls(news, errors)

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print("VALIDATION OK")
    for warning in warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
