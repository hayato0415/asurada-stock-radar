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
META_PATH = DATA_DIR / "factor-scores.meta.json"
DAILY_PATH = DATA_DIR / "ai-top10-daily.json"
HISTORY_PATH = DATA_DIR / "ai-top10-history.json"
WEEKLY_PATH = DATA_DIR / "ai-persistence-weekly.json"
MONTHLY_PATH = DATA_DIR / "ai-persistence-monthly.json"
SNAPSHOT_DIR = ROOT / "data" / "history" / "ai-top10"

EXPECTED_WEIGHTS = {
    "fundamentalScore": 0.30,
    "technicalScore": 0.30,
    "chipScore": 0.25,
    "turnoverScore": 0.15,
}

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


def validate_scores(
    scores: list[dict[str, Any]],
    status: dict[str, Any],
    meta: dict[str, Any],
    target_date: str | None,
) -> int:
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
    codes = [str(row.get("code") or "") for row in scores]
    if any(not code for code in codes) or len(set(codes)) != len(codes):
        return fail("factor-scores.json contains missing or duplicate stock codes.")

    weights = meta.get("weights") if isinstance(meta, dict) else None
    if weights != EXPECTED_WEIGHTS:
        return fail(f"factor-scores.meta.json weights are not the official 30/30/25/15 weights: {weights}")

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

        expected_total = round(
            row["fundamentalScore"] * EXPECTED_WEIGHTS["fundamentalScore"]
            + row["technicalScore"] * EXPECTED_WEIGHTS["technicalScore"]
            + row["chipScore"] * EXPECTED_WEIGHTS["chipScore"]
            + row["turnoverScore"] * EXPECTED_WEIGHTS["turnoverScore"],
            1,
        )
        if not math.isclose(row["totalScore"], expected_total, abs_tol=0.11):
            return fail(
                f"{label} totalScore {row['totalScore']} does not match official weighted total {expected_total}."
            )

        if row["totalScore"] > previous_score:
            return fail(f"{label} totalScore order is not descending.")
        previous_score = row["totalScore"]

        if "newsScore" in row:
            return fail(f"{label} contains forbidden newsScore field.")

    return 0


def validate_persistence(expected_date: str, status: dict[str, Any]) -> int:
    persistence_status = status.get("persistence_status")
    if not isinstance(persistence_status, dict) or persistence_status.get("ok") is not True:
        return fail(
            "factor-scores.status.json persistence_status is not successful: "
            f"{persistence_status or '--'}"
        )

    required = [DAILY_PATH, HISTORY_PATH, WEEKLY_PATH, MONTHLY_PATH]
    missing = [path.name for path in required if not path.exists()]
    if missing:
        return fail(f"missing persistence outputs: {', '.join(missing)}")

    daily = read_json(DAILY_PATH)
    history = read_json(HISTORY_PATH)
    weekly = read_json(WEEKLY_PATH)
    monthly = read_json(MONTHLY_PATH)
    for path, payload in (
        (DAILY_PATH, daily),
        (HISTORY_PATH, history),
        (WEEKLY_PATH, weekly),
        (MONTHLY_PATH, monthly),
    ):
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return fail(f"{path.name} is not a successful JSON object.")
        if payload.get("latest_trade_date") != expected_date:
            return fail(
                f"{path.name} latest_trade_date {payload.get('latest_trade_date')} "
                f"does not match {expected_date}."
            )

    daily_items = daily.get("items")
    if not isinstance(daily_items, list) or len(daily_items) != 10:
        return fail(f"ai-top10-daily.json must contain exactly 10 rows, got {len(daily_items or [])}.")
    daily_ranks = [item.get("rank") for item in daily_items if isinstance(item, dict)]
    daily_codes = [str(item.get("code") or "") for item in daily_items if isinstance(item, dict)]
    if daily_ranks != list(range(1, 11)):
        return fail("ai-top10-daily.json rank must be continuous from 1 to 10.")
    if len(set(daily_codes)) != 10 or any(not code for code in daily_codes):
        return fail("ai-top10-daily.json contains missing or duplicate stock codes.")
    if any(item.get("dataDate") != expected_date for item in daily_items):
        return fail("ai-top10-daily.json contains a row with the wrong dataDate.")

    history_dates = history.get("tradingDates")
    history_items = history.get("items")
    if not isinstance(history_dates, list) or not isinstance(history_items, list):
        return fail("ai-top10-history.json must contain tradingDates and items arrays.")
    if history_dates != sorted(set(history_dates)):
        return fail("ai-top10-history.json contains duplicate or unsorted snapshot dates.")
    if not history_dates or history_dates[-1] != expected_date or len(history_dates) != len(history_items):
        return fail("ai-top10-history.json latest date or item count is invalid.")

    for snapshot in history_items:
        if not isinstance(snapshot, dict):
            return fail("ai-top10-history.json contains a non-object snapshot.")
        snapshot_date = str(snapshot.get("dataDate") or "")
        snapshot_items = snapshot.get("items")
        if not isinstance(snapshot_items, list) or len(snapshot_items) != 10:
            return fail(f"history snapshot {snapshot_date or '--'} does not contain exactly 10 rows.")
        snapshot_path = SNAPSHOT_DIR / f"{snapshot_date}.json"
        if not snapshot_path.exists():
            return fail(f"immutable snapshot file is missing: {snapshot_path.relative_to(ROOT)}")
        disk_snapshot = read_json(snapshot_path)
        if disk_snapshot != snapshot:
            return fail(f"history snapshot {snapshot_date} differs from its immutable file.")

    expected_week_dates = history_dates[-5:]
    expected_month_dates = history_dates[-20:]
    if weekly.get("tradingDates") != expected_week_dates:
        return fail(
            f"weekly summary does not use the latest 5 trading days: {weekly.get('tradingDates')}"
        )
    if monthly.get("tradingDates") != expected_month_dates:
        return fail(
            f"monthly summary does not use the latest 20 trading days: {monthly.get('tradingDates')}"
        )
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
    if not META_PATH.exists():
        return fail("factor-scores.meta.json does not exist.")
    scores = read_json(SCORES_PATH)
    meta = read_json(META_PATH)
    if not isinstance(scores, list):
        return fail("factor-scores.json must be an array.")

    if args.target_date and status.get("latest_trade_date") != args.target_date:
        return fail(
            f"status latest_trade_date {status.get('latest_trade_date')} does not match target {args.target_date}."
        )

    score_result = validate_scores(scores, status, meta, args.target_date)
    if score_result:
        return score_result
    expected_date = args.target_date or str(status.get("latest_trade_date") or "")
    return validate_persistence(expected_date, status)


if __name__ == "__main__":
    raise SystemExit(main())
