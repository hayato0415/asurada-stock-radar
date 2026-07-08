#!/usr/bin/env python
"""Run all ASURADA Stock Radar data builders as one coordinated refresh.

The individual builders remain reusable, but scheduled production updates
should go through this wrapper so all status files describe the same run.
Failures are recorded without deleting previously usable JSON.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except ZoneInfoNotFoundError:
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")

DATA_PROCESSED = ROOT / "data" / "processed"
DOCS_DATA = ROOT / "docs" / "data"
DOCS_PROCESSED = DOCS_DATA / "processed"

UPDATE_LOG = DATA_PROCESSED / "update_log.json"
DOCS_UPDATE_STATUS = DOCS_DATA / "update_status.json"
FACTOR_STATUS = DATA_PROCESSED / "factor-scores.status.json"
FACTOR_META = DATA_PROCESSED / "factor-scores.meta.json"
DOCS_FACTOR_STATUS = DOCS_PROCESSED / "factor-scores.status.json"
DOCS_FACTOR_META = DOCS_PROCESSED / "factor-scores.meta.json"

FACTOR_NEWS_EXCLUSION_REASON = (
    "\u65b0\u805e\u9762\u4e0d\u7d0d\u5165\u5206\u6578\u3001"
    "\u4e0d\u7d0d\u5165\u6392\u540d\u3001"
    "\u4e0d\u4f5c\u70ba\u7be9\u9078\u689d\u4ef6\u3002"
)

STEPS = [
    ("full_market_data", "scripts/update_full_market_data.py"),
    ("ai_scorecards", "scripts/build_ai_scorecards.py"),
    ("validate_ai_scoring", "scripts/validate_ai_scoring.py"),
    ("stock_metrics", "scripts/update_stock_metrics.py"),
    ("radar_close_data", "scripts/update_radar.py"),
    ("factor_scores", "scripts/update_factor_scores.py"),
    ("validate_factor_scores", "scripts/validate_factor_scores.py"),
]

WATCHED_FILES = [
    DATA_PROCESSED / "stocks_master.json",
    DATA_PROCESSED / "stock_metrics_daily.json",
    DATA_PROCESSED / "ai_scores_daily.json",
    DATA_PROCESSED / "theme_stats.json",
    DATA_PROCESSED / "news_events.json",
    DATA_PROCESSED / "factor-scores.json",
    DATA_PROCESSED / "factor-scores.status.json",
    DATA_PROCESSED / "factor-scores.meta.json",
    DOCS_DATA / "radar.json",
    DOCS_DATA / "update_status.json",
    DOCS_PROCESSED / "factor-scores.json",
    DOCS_PROCESSED / "factor-scores.status.json",
    DOCS_PROCESSED / "factor-scores.meta.json",
]


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(microsecond=0)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tail(text: str, limit: int = 1800) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def run_step(name: str, script: str) -> dict[str, Any]:
    started = now_taipei().isoformat()
    command = [sys.executable, str(ROOT / script)]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
        ok = result.returncode == 0
        return {
            "name": name,
            "script": script,
            "ok": ok,
            "returncode": result.returncode,
            "started_at": started,
            "finished_at": now_taipei().isoformat(),
            "stdout_tail": tail(result.stdout),
            "stderr_tail": tail(result.stderr),
            "error": "" if ok else tail(result.stderr or result.stdout or f"exit {result.returncode}"),
        }
    except Exception as exc:
        return {
            "name": name,
            "script": script,
            "ok": False,
            "returncode": None,
            "started_at": started,
            "finished_at": now_taipei().isoformat(),
            "stdout_tail": "",
            "stderr_tail": "",
            "error": str(exc),
        }


def get_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "scores", "stocks", "rows", "rankings", "events", "files"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def pick_first(payload: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    return text[:10]


def file_status(path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    items = get_items(payload)
    updated_at = pick_first(payload, ("updated_at", "generated_at", "last_updated"))
    content_date = pick_first(
        payload,
        (
            "latest_trade_date",
            "content_latest_at",
            "trade_date",
            "date",
            "market_date",
            "data_date",
            "updatedAt",
        ),
    )
    if not content_date and items and isinstance(items[0], dict):
        content_date = pick_first(items[0], ("trade_date", "market_date", "date", "updated_at", "updatedAt"))

    ok_value = payload.get("ok") if isinstance(payload, dict) else None
    status_value = payload.get("status") if isinstance(payload, dict) else None
    failed = ok_value is False or str(status_value).lower() in {"failed", "error", "partial_failed"}
    stale = bool(payload.get("stale")) if isinstance(payload, dict) else False

    count = payload.get("items_count") if isinstance(payload, dict) else None
    if count is None and isinstance(payload, dict):
        count = payload.get("count")
    if count is None:
        count = len(items)

    reasons: list[str] = []
    if isinstance(payload, dict):
        for key in ("failed_reasons", "errors", "warnings"):
            value = payload.get(key)
            if isinstance(value, list):
                reasons.extend(str(item) for item in value if item)
            elif value:
                reasons.append(str(value))
        message = payload.get("message") or payload.get("stale_reason")
        if message:
            reasons.append(str(message))

    return {
        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
        "exists": path.exists(),
        "status": "failed" if failed else ("stale" if stale else ("ok" if path.exists() else "missing")),
        "updated_at": updated_at or "",
        "content_latest_at": normalize_date(content_date),
        "items_count": count,
        "failed_reasons": reasons,
        "previous_data_preserved": bool(payload.get("previous_data_preserved")) if isinstance(payload, dict) else False,
    }


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=TAIPEI)
    except ValueError:
        return None


def business_days_between(start: datetime, end: datetime) -> int:
    if start.date() >= end.date():
        return 0
    current = start.date() + timedelta(days=1)
    count = 0
    while current <= end.date():
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def latest_trade_date_from(files: list[dict[str, Any]]) -> str:
    dates = [status["content_latest_at"] for status in files if status.get("content_latest_at")]
    return max(dates) if dates else ""


def build_freshness_warning(latest_trade_date: str, now: datetime) -> tuple[list[str], list[str]]:
    warning: list[str] = []
    stale_files: list[str] = []
    latest = parse_date(latest_trade_date)
    if not latest:
        return ["Unable to determine latest trade date. Check source data."], stale_files

    lag = business_days_between(latest, now)
    if now.time() < time(15, 20) and lag <= 1:
        warning.append("Before Taipei 15:20 close-data refresh window; previous trading day is acceptable.")
    elif lag > 1:
        warning.append(f"Data is behind: latest trade date {latest_trade_date}, current Taipei time {now:%Y-%m-%d %H:%M}.")
        stale_files.append("latest_trade_date")
    return warning, stale_files


def sync_factor_status(step_results: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    status = read_json(DOCS_FACTOR_STATUS, read_json(FACTOR_STATUS, {}))
    if not isinstance(status, dict):
        status = {}

    factor_failures = [
        step for step in step_results
        if step["name"] in {"factor_scores", "validate_factor_scores"} and not step["ok"]
    ]
    if factor_failures:
        reasons = list(status.get("failed_reasons") or [])
        reasons.extend(step["error"] for step in factor_failures if step.get("error"))
        status.update({
            "ok": False,
            "updated_at": now.isoformat(),
            "attempted_at": now.isoformat(),
            "previous_data_preserved": True,
            "failed_reasons": reasons,
        })
    else:
        status.setdefault("ok", True)
        status.setdefault("failed_reasons", [])
        status.setdefault("previous_data_preserved", False)
        status["unified_checked_at"] = now.isoformat()

    write_json(FACTOR_STATUS, status)
    write_json(DOCS_FACTOR_STATUS, status)
    return status


def sync_factor_meta(now: datetime, source_status: list[dict[str, Any]], latest_trade_date: str) -> dict[str, Any]:
    meta = read_json(DOCS_FACTOR_META, read_json(FACTOR_META, {}))
    if not isinstance(meta, dict):
        meta = {}
    meta["unified_update_at"] = now.isoformat()
    meta["latest_trade_date"] = meta.get("latest_trade_date") or latest_trade_date
    meta["news_score"] = {
        "weight": 0,
        "included": False,
        "reason": FACTOR_NEWS_EXCLUSION_REASON,
    }
    meta["source_status_summary"] = {
        step["name"]: "ok" if step["ok"] else "failed"
        for step in source_status
        if step["name"] in {"factor_scores", "validate_factor_scores"}
    }
    write_json(FACTOR_META, meta)
    write_json(DOCS_FACTOR_META, meta)
    return meta


def write_unified_status(step_results: list[dict[str, Any]]) -> dict[str, Any]:
    now = now_taipei()
    factor_status = sync_factor_status(step_results, now)
    sync_factor_meta(now, step_results, str(factor_status.get("latest_trade_date") or ""))

    file_statuses = [file_status(path) for path in WATCHED_FILES]
    latest_trade_date = latest_trade_date_from(file_statuses)
    warning, stale_files = build_freshness_warning(latest_trade_date, now)

    failed_reasons = [
        f"{step['name']}: {step['error']}"
        for step in step_results
        if not step["ok"] and step.get("error")
    ]
    for status in file_statuses:
        if status["status"] in {"failed", "missing"}:
            failed_reasons.extend(f"{status['file']}: {reason}" for reason in status["failed_reasons"] or [status["status"]])
        if status.get("previous_data_preserved"):
            failed_reasons.append(f"{status['file']}: update failed; previous usable data was preserved.")
        if status["status"] == "stale":
            stale_files.append(status["file"])

    overall_status = "ok"
    if failed_reasons:
        overall_status = "partial_failed"
    if stale_files:
        overall_status = "stale" if overall_status == "ok" else overall_status

    payload = {
        "updated_at": now.isoformat(),
        "latest_trade_date": latest_trade_date,
        "status": overall_status,
        "each_file_status": file_statuses,
        "stale_files": sorted(set(stale_files)),
        "failed_reasons": failed_reasons,
        "warning": warning,
        "source_status": step_results,
        "items": [
            {
                "file": item["file"],
                "updated_at": item["updated_at"],
                "content_latest_at": item["content_latest_at"],
                "count": item["items_count"],
                "status": item["status"],
                "error": "; ".join(item["failed_reasons"]),
            }
            for item in file_statuses
        ],
    }

    write_json(UPDATE_LOG, payload)

    existing_status = read_json(DOCS_UPDATE_STATUS, {})
    if not isinstance(existing_status, dict):
        existing_status = {}
    existing_status.update({
        "status": overall_status,
        "updated_at": now.isoformat(),
        "latest_trade_date": latest_trade_date,
        "trade_date": latest_trade_date or existing_status.get("trade_date"),
        "message": "Unified full refresh completed" if overall_status == "ok" else "Unified full refresh completed with issues",
        "each_file_status": file_statuses,
        "stale_files": sorted(set(stale_files)),
        "failed_reasons": failed_reasons,
        "warning": warning,
        "source_status": step_results,
    })
    write_json(DOCS_UPDATE_STATUS, existing_status)
    return payload


def main() -> int:
    results = [run_step(name, script) for name, script in STEPS]
    status = write_unified_status(results)

    print(f"Unified update status: {status['status']}")
    print(f"Updated at: {status['updated_at']}")
    print(f"Latest trade date: {status.get('latest_trade_date') or '--'}")
    if status["failed_reasons"]:
        print("Failed reasons:")
        for reason in status["failed_reasons"]:
            print(f"- {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

