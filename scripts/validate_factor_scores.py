#!/usr/bin/env python
"""Validate factor-score outputs before publishing.

The validator is deliberately strict about fake freshness:
`updated_at` alone is not enough.  When the update status is OK, rows must
carry the same content date as the official quote date.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"
SCORES_PATH = DATA_DIR / "factor-scores.json"
STATUS_PATH = DATA_DIR / "factor-scores.status.json"

CRITICAL_FIELDS = [
    "code",
    "name",
    "close",
    "changePercent",
    "volume",
    "turnoverRate",
    "fundamentalScore",
    "technicalScore",
    "chipScore",
    "turnoverScore",
    "totalScore",
    "dataDate",
]


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fail(message: str) -> int:
    print(f"[factor-score validate] ERROR: {message}", file=sys.stderr)
    return 1


def warn(message: str) -> None:
    print(f"[factor-score validate] WARNING: {message}")


def validate_scores(scores: list[dict[str, Any]], status: dict[str, Any], target_date: str | None) -> int:
    if not scores:
        return fail("factor-scores.json is empty while status is ok.")
    if len(scores) > 100:
        return fail("factor-scores.json contains more than 100 rows.")

    expected_date = target_date or status.get("latest_trade_date")
    if not expected_date:
        return fail("status.latest_trade_date is missing.")

    ranks = [row.get("rank") for row in scores]
    expected_ranks = list(range(1, len(scores) + 1))
    if ranks != expected_ranks:
        return fail(f"rank sequence is not continuous: expected 1..{len(scores)}.")

    previous_score = float("inf")
    for row in scores:
        label = f"{row.get('code', '?')} {row.get('name', '')}".strip()
        for field in CRITICAL_FIELDS:
            if row.get(field) is None or row.get(field) == "":
                return fail(f"{label} missing critical field: {field}")

        if row.get("dataDate") != expected_date:
            return fail(f"{label} dataDate {row.get('dataDate')} does not match expected {expected_date}.")

        for score_field in ["fundamentalScore", "technicalScore", "chipScore", "turnoverScore", "totalScore"]:
            value = row.get(score_field)
            if not is_number(value) or value < 0 or value > 100:
                return fail(f"{label} invalid {score_field}: {value}")

        if row["totalScore"] > previous_score:
            return fail(f"{label} totalScore order is not descending.")
        previous_score = row["totalScore"]

        if "newsScore" in row:
            return fail(f"{label} contains forbidden newsScore field.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", help="Expected official quote date, YYYY-MM-DD.")
    args = parser.parse_args()

    if not STATUS_PATH.exists():
        return fail("factor-scores.status.json does not exist.")
    status = read_json(STATUS_PATH)

    if not status.get("ok"):
        reasons = status.get("failed_reasons") or status.get("warnings") or []
        if not reasons:
            return fail("status is failed but has no failed_reasons/warnings.")
        if not status.get("previous_data_preserved"):
            return fail("status is failed but previous_data_preserved is not true.")
        warn("official update failed; previous factor-scores.json is intentionally preserved.")
        for reason in reasons:
            warn(str(reason))
        return 0

    if not SCORES_PATH.exists():
        return fail("factor-scores.json does not exist.")
    scores = read_json(SCORES_PATH)
    if not isinstance(scores, list):
        return fail("factor-scores.json must be an array.")

    if args.target_date and status.get("latest_trade_date") != args.target_date:
        return fail(
            f"status latest_trade_date {status.get('latest_trade_date')} does not match target {args.target_date}."
        )

    return validate_scores(scores, status, args.target_date)


if __name__ == "__main__":
    raise SystemExit(main())
