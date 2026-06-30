#!/usr/bin/env python3
"""Build lightweight MoneyDJ concepts JSON from crawler CSV outputs."""

from __future__ import annotations

import csv
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"
try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")

CATEGORIES = DATA / "moneydj_concept_categories.csv"
STOCKS = DATA / "moneydj_concept_stocks.csv"


def now_text() -> str:
    return datetime.now(TAIPEI).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"{path} 不存在")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def main() -> None:
    categories = read_csv(CATEGORIES)
    stocks = read_csv(STOCKS)
    if not categories:
        raise SystemExit("MoneyDJ categories CSV is empty")
    if not stocks:
        raise SystemExit("MoneyDJ stocks CSV is empty")

    stocks_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in stocks:
        code = (row.get("concept_code") or "").strip()
        if not code:
            continue
        stock_id = (row.get("stock_id") or "").strip()
        stock_name = (row.get("stock_name") or "").strip()
        if not stock_id or not stock_name:
            continue
        stocks_by_code.setdefault(code, []).append(
            {
                "stock_id": stock_id,
                "stock_name": stock_name,
            }
        )

    concepts: list[dict[str, Any]] = []
    for row in categories:
        code = (row.get("concept_code") or "").strip()
        name = (row.get("concept_name") or "").strip()
        if not code or not name:
            continue
        concepts.append(
            {
                "concept_id": code,
                "concept_code": code,
                "concept_name": name,
                "source": "MoneyDJ",
                "source_url": f"https://www.moneydj.com/z/zg/zge/zge_{code}_1.djhtm",
                "display_order": int(row.get("display_order") or len(concepts) + 1),
                "stocks": stocks_by_code.get(code, []),
            }
        )

    payload = {
        "updated_at": now_text(),
        "generated_at": now_text(),
        "source": "MoneyDJ",
        "source_count": 1,
        "concept_count": len(concepts),
        "stock_relation_count": sum(len(item["stocks"]) for item in concepts),
        "concepts": concepts,
    }

    write_json_atomic(DOCS_DATA / "concepts-moneydj.json", payload)
    write_json_atomic(DATA / "concepts-moneydj.json", payload)
    print(
        f"concepts-moneydj.json built: {payload['concept_count']} concepts, "
        f"{payload['stock_relation_count']} stock relations"
    )


if __name__ == "__main__":
    main()
