#!/usr/bin/env python3
"""Validate and publish the concept index taxonomy.

This script is deliberately conservative. It does not scrape external sites.
It validates a manually maintained taxonomy JSON and writes the static file
used by GitHub Pages.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
OUTPUT = DOCS_DATA / "concepts-taxonomy.json"
MANUAL_SOURCE = ROOT / "data" / "manual_concepts_taxonomy.json"

VALID_GROUPS = {
    "listed",
    "otc",
    "electronics",
    "supplyChain",
    "themes",
    "groups",
    "indices",
    "manual",
}
VALID_CONFIDENCE = {"A", "B", "C", "D", "E"}
VALID_COVERAGE = {"complete", "partial", "needs_fill"}


def load_source() -> dict:
    source = MANUAL_SOURCE if MANUAL_SOURCE.exists() else OUTPUT
    if not source.exists():
        raise FileNotFoundError(
            "No taxonomy source found. Create data/manual_concepts_taxonomy.json "
            "or docs/data/concepts-taxonomy.json first."
        )
    with source.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_stock(stock: dict, category: dict) -> dict:
    for key in ("code", "name"):
        if not str(stock.get(key, "")).strip():
            raise ValueError(f"Stock in {category.get('id')} missing {key}")
    confidence = stock.get("confidence") or category.get("confidence") or "C"
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(f"Invalid stock confidence {confidence} for {stock.get('code')}")
    normalized = dict(stock)
    normalized["code"] = str(stock["code"]).strip()
    normalized["name"] = str(stock["name"]).strip()
    normalized["market"] = str(stock.get("market") or "").strip()
    normalized["confidence"] = confidence
    normalized["source_count"] = int(stock.get("source_count") or 1)
    normalized["data_quality"] = stock.get("data_quality") or "low"
    normalized["evidence"] = stock.get("evidence") if isinstance(stock.get("evidence"), list) else []
    return normalized


def normalize_category(category: dict) -> dict:
    for key in ("id", "name", "display_group", "type"):
        if not str(category.get(key, "")).strip():
            raise ValueError(f"Category missing {key}")
    if category["display_group"] not in VALID_GROUPS:
        raise ValueError(f"Invalid display_group {category['display_group']} for {category['id']}")
    confidence = category.get("confidence") or "C"
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(f"Invalid confidence {confidence} for {category['id']}")
    coverage = category.get("coverage_status") or category.get("data_quality") or "partial"
    if coverage not in VALID_COVERAGE:
        coverage = "partial"
    normalized = dict(category)
    normalized["aliases"] = category.get("aliases") if isinstance(category.get("aliases"), list) else []
    normalized["source_count"] = int(category.get("source_count") or len(category.get("sources") or []) or 1)
    normalized["sources"] = category.get("sources") if isinstance(category.get("sources"), list) else []
    normalized["confidence"] = confidence
    normalized["data_quality"] = category.get("data_quality") or coverage
    normalized["coverage_status"] = coverage
    normalized["representative_stocks"] = [
        normalize_stock(stock, normalized) for stock in category.get("representative_stocks", [])
    ]
    normalized["all_stocks"] = [
        normalize_stock(stock, normalized) for stock in category.get("all_stocks", [])
    ]
    normalized["stock_count"] = int(category.get("stock_count") or len(normalized["all_stocks"]))
    normalized["url"] = category.get("url") or f"concept-detail.html?id={normalized['id']}"
    normalized["source_breakdown"] = (
        category.get("source_breakdown") if isinstance(category.get("source_breakdown"), list) else []
    )
    normalized["coverage_check"] = (
        category.get("coverage_check") if isinstance(category.get("coverage_check"), dict) else {}
    )
    return normalized


def build_taxonomy() -> dict:
    raw = load_source()
    categories = raw.get("categories")
    if not isinstance(categories, list) or not categories:
        raise ValueError("taxonomy categories must be a non-empty list")
    return {
        "generated_at": raw.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_policy": raw.get("source_policy") or {},
        "categories": [normalize_category(category) for category in categories],
    }


def main() -> int:
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    taxonomy = build_taxonomy()
    temp = OUTPUT.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(taxonomy, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    shutil.move(str(temp), str(OUTPUT))
    print(f"concept index categories: {len(taxonomy['categories'])}")
    print(f"output: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
