from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")

NOISE_KEYWORDS = [
    "指數成分股",
    "基金",
    "減碼",
    "ETF",
    "MSCI",
    "臺灣50",
    "臺灣中型100",
    "資訊科技指數",
]


def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def clean_concept_name(name: str) -> str:
    text = str(name or "").strip()
    return text.removesuffix("概念股").strip()


def is_noise_concept(name: str) -> bool:
    text = str(name or "")
    return any(keyword in text for keyword in NOISE_KEYWORDS)


def add_entry(index: dict, stock_id: str, entry: dict) -> None:
    code = str(stock_id or "").strip()
    if not code:
        return
    bucket = index.setdefault(code, {"concepts": [], "all_concepts": []})
    key = (entry.get("concept_name"), entry.get("source"), entry.get("source_url"))
    existing = {
        (item.get("concept_name"), item.get("source"), item.get("source_url"))
        for item in bucket["all_concepts"]
    }
    if key in existing:
        return
    bucket["all_concepts"].append(entry)
    if not is_noise_concept(entry.get("concept_name", "")):
        bucket["concepts"].append(entry)


def build_from_moneydj(index: dict) -> int:
    data = read_json(DOCS_DATA / "concepts-moneydj.json", {})
    concepts = data.get("concepts", []) if isinstance(data, dict) else []
    count = 0
    for concept in concepts:
        concept_name = clean_concept_name(concept.get("concept_name", ""))
        concept_code = concept.get("concept_code") or concept.get("concept_id") or ""
        source_url = concept.get("source_url") or ""
        for stock in concept.get("stocks", []) or []:
            if not isinstance(stock, dict):
                continue
            add_entry(index, stock.get("stock_id"), {
                "concept_name": concept_name,
                "concept_code": concept_code,
                "source": "MoneyDJ",
                "source_url": source_url,
                "confidence": "B",
            })
            count += 1
    return count


def build_from_manual(index: dict) -> int:
    path = DOCS_DATA / "concepts-manual.csv"
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            concept_name = clean_concept_name(row.get("concept_name", ""))
            stock_id = row.get("stock_id", "")
            if not concept_name or not stock_id:
                continue
            add_entry(index, stock_id, {
                "concept_name": concept_name,
                "concept_code": "",
                "source": row.get("source") or "手動補充",
                "source_url": row.get("source_url") or "",
                "confidence": "C",
            })
            count += 1
    return count


def sort_index(index: dict) -> dict:
    result = {}
    for code, payload in sorted(index.items()):
        concepts = payload.get("concepts", [])
        all_concepts = payload.get("all_concepts", [])
        concepts.sort(key=lambda item: (item.get("source") != "MoneyDJ", item.get("concept_name", "")))
        all_concepts.sort(key=lambda item: (item.get("source") != "MoneyDJ", item.get("concept_name", "")))
        result[code] = {
            "concept_count": len(concepts),
            "all_concept_count": len(all_concepts),
            "concepts": concepts,
        }
    return result


def main() -> None:
    index: dict = {}
    moneydj_count = build_from_moneydj(index)
    manual_count = build_from_manual(index)
    payload = {
        "updated_at": datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S Asia/Taipei"),
        "source_policy": "以 MoneyDJ 主資料庫為主，合併 concepts-manual.csv 手動補充；前台過濾指數成分股與基金類雜訊。",
        "source_files": ["concepts-moneydj.json", "concepts-manual.csv"],
        "stock_count": len(index),
        "moneydj_relation_count": moneydj_count,
        "manual_relation_count": manual_count,
        "stocks": sort_index(index),
    }
    output = DOCS_DATA / "stock-concepts-index.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({
        "success": True,
        "output": str(output.relative_to(ROOT)).replace("\\", "/"),
        "stock_count": payload["stock_count"],
        "moneydj_relation_count": moneydj_count,
        "manual_relation_count": manual_count,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
