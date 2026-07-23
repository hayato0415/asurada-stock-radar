#!/usr/bin/env python
"""Unified ASURADA site data refresh.

This script is the single scheduled entry point for the GitHub Pages data
pipeline.  The older builders still do the actual source-specific work, but
production schedules should call only this wrapper so every page sees the same
run id, data version and latest trade date.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except ZoneInfoNotFoundError:
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")

DATA_DIR = ROOT / "data"
DATA_PROCESSED = DATA_DIR / "processed"
DOCS_DATA = ROOT / "docs" / "data"
DOCS_PROCESSED = DOCS_DATA / "processed"

SITE_META = DOCS_DATA / "site_meta.json"
DATA_STATUS = DOCS_DATA / "data_status.json"
ROOT_SITE_META = DATA_DIR / "site_meta.json"
ROOT_DATA_STATUS = DATA_DIR / "data_status.json"
DOCS_UPDATE_STATUS = DOCS_DATA / "update_status.json"
ROOT_UPDATE_STATUS = DATA_DIR / "update_status.json"
ROOT_UPDATE_LOG = DATA_PROCESSED / "update_log.json"
DOCS_UPDATE_LOG = DOCS_PROCESSED / "update_log.json"

STEPS = [
    ("news_events", "scripts/update_news_events.py"),
    ("full_market_data", "scripts/update_full_market_data.py"),
    ("ai_scorecards", "scripts/build_ai_scorecards.py"),
    ("validate_ai_scoring", "scripts/validate_ai_scoring.py"),
    ("stock_metrics", "scripts/update_stock_metrics.py"),
    ("radar_close_data", "scripts/update_radar.py"),
    ("factor_scores", "scripts/update_factor_scores.py"),
    ("validate_factor_scores", "scripts/validate_factor_scores.py"),
    ("ai_validation", "scripts/update_ai_validation.py"),
    ("validate_ai_validation", "scripts/validate_ai_validation.py"),
]

STATUS_TARGETS = [
    DOCS_DATA / "radar.json",
    DOCS_UPDATE_STATUS,
    DOCS_PROCESSED / "stocks_master.json",
    DOCS_PROCESSED / "stock_metrics_daily.json",
    DOCS_PROCESSED / "ai_scores_daily.json",
    DOCS_PROCESSED / "factor-scores.json",
    DOCS_PROCESSED / "factor-scores.status.json",
    DOCS_PROCESSED / "factor-scores.meta.json",
    DOCS_PROCESSED / "ai-top10-daily.json",
    DOCS_PROCESSED / "ai-top10-history.json",
    DOCS_PROCESSED / "ai-persistence-weekly.json",
    DOCS_PROCESSED / "ai-persistence-monthly.json",
    DOCS_PROCESSED / "ai-validation-detail.json",
    DOCS_PROCESSED / "ai-validation-summary.json",
    DOCS_PROCESSED / "ai-validation-portfolio.json",
    DOCS_PROCESSED / "ai-factor-performance.json",
    DOCS_PROCESSED / "ai-validation-status.json",
    DOCS_PROCESSED / "theme_stats.json",
    DOCS_PROCESSED / "news_events.json",
]

CRITICAL_SYNC_FILES = {
    "docs/data/radar.json",
    "docs/data/update_status.json",
    "docs/data/processed/stock_metrics_daily.json",
    "docs/data/processed/ai_scores_daily.json",
    "docs/data/processed/factor-scores.json",
    "docs/data/processed/factor-scores.status.json",
    "docs/data/processed/factor-scores.meta.json",
    "docs/data/processed/ai-top10-daily.json",
    "docs/data/processed/ai-top10-history.json",
    "docs/data/processed/ai-persistence-weekly.json",
    "docs/data/processed/ai-persistence-monthly.json",
    "docs/data/processed/ai-validation-detail.json",
    "docs/data/processed/ai-validation-summary.json",
    "docs/data/processed/ai-validation-portfolio.json",
    "docs/data/processed/ai-factor-performance.json",
    "docs/data/processed/ai-validation-status.json",
}

COMMON_KEYS = {
    "run_id",
    "generated_at",
    "latest_trade_date",
    "data_version",
    "source_pipeline",
}

FACTOR_OUTPUT_NAMES = {
    "factor-scores.json",
    "factor-scores.status.json",
    "factor-scores.meta.json",
    "factor-quote-history.json",
    "ai-top10-daily.json",
    "ai-top10-history.json",
    "ai-persistence-weekly.json",
    "ai-persistence-monthly.json",
}
FACTOR_OUTPUTS = tuple(DATA_PROCESSED / name for name in sorted(FACTOR_OUTPUT_NAMES))
FACTOR_TOP10_HISTORY = DATA_DIR / "history" / "ai-top10"
AI_VALIDATION_OUTPUT_NAMES = {
    "ai-validation-detail.json",
    "ai-validation-summary.json",
    "ai-validation-portfolio.json",
    "ai-factor-performance.json",
    "ai-validation-market-history.json",
}
AI_VALIDATION_STATUS_NAME = "ai-validation-status.json"
AI_VALIDATION_OUTPUTS = tuple(
    DATA_PROCESSED / name for name in sorted(AI_VALIDATION_OUTPUT_NAMES)
)
AI_VALIDATION_HISTORY = DATA_DIR / "history" / "ai-validation"
NEWS_EVENTS_NAME = "news_events.json"


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(microsecond=0)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: Any) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_bytes_atomic(path, content)


def snapshot_files(paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def restore_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            write_bytes_atomic(path, content)


def snapshot_directory(path: Path) -> dict[Path, bytes]:
    if not path.exists():
        return {}
    return {item: item.read_bytes() for item in path.glob("*.json") if item.is_file()}


def restore_directory(path: Path, snapshot: dict[Path, bytes]) -> None:
    if path.exists():
        for item in path.glob("*.json"):
            if item not in snapshot:
                item.unlink(missing_ok=True)
    for item, content in snapshot.items():
        write_bytes_atomic(item, content)


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
            timeout=1200,
            check=False,
        )
        ok = result.returncode == 0
        failure_output = "\n".join(
            part
            for part in (tail(result.stdout), tail(result.stderr))
            if part
        ) or f"exit {result.returncode}"
        return {
            "name": name,
            "script": script,
            "ok": ok,
            "returncode": result.returncode,
            "started_at": started,
            "finished_at": now_taipei().isoformat(),
            "stdout_tail": tail(result.stdout),
            "stderr_tail": tail(result.stderr),
            "error": "" if ok else failure_output,
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


def normalize_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    return text[:10]


def first_existing(payload: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def payload_date(payload: Any) -> str:
    value = first_existing(
        payload,
        (
            "latest_trade_date",
            "trade_date",
            "content_latest_at",
            "market_date",
            "date",
            "data_date",
        ),
    )
    if not value:
        items = get_items(payload)
        if items and isinstance(items[0], dict):
            value = first_existing(
                items[0],
                ("latest_trade_date", "trade_date", "market_date", "date", "dataDate", "data_date"),
            )
    return normalize_date(value)


def payload_count(payload: Any) -> int:
    if isinstance(payload, dict):
        for key in ("items_count", "count", "rows", "rows_written", "stock_master_count"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
    return len(get_items(payload))


def sync_processed_to_docs() -> None:
    DOCS_PROCESSED.mkdir(parents=True, exist_ok=True)
    if not DATA_PROCESSED.exists():
        return
    for source in DATA_PROCESSED.glob("*.json"):
        shutil.copy2(source, DOCS_PROCESSED / source.name)


def copy_status_sidecars() -> None:
    if DOCS_UPDATE_STATUS.exists():
        shutil.copy2(DOCS_UPDATE_STATUS, ROOT_UPDATE_STATUS)


def collect_candidate_dates() -> list[str]:
    dates: list[str] = []
    candidates = [
        DOCS_DATA / "radar.json",
        DATA_PROCESSED / "stock_metrics_daily.json",
    ]
    for path in candidates:
        payload = read_json(path, {})
        if isinstance(payload, dict):
            status = str(payload.get("status", "")).lower()
            if payload.get("ok") is False or status in {"failed", "error", "partial_failed"}:
                continue
        date = payload_date(payload)
        if date:
            dates.append(date)
    return dates


def latest_trade_date() -> str:
    dates = collect_candidate_dates()
    # The site date represents the newest date shared by both authoritative
    # market snapshots.  Using the minimum prevents one early/late source from
    # making the whole site claim a date that part of the market has not reached.
    return min(dates) if dates else ""


def make_metadata(now: datetime, latest: str) -> dict[str, str]:
    run_id = os.getenv("GITHUB_RUN_ID") or now.strftime("%Y%m%d%H%M%S")
    version_date = latest.replace("-", "") if latest else now.strftime("%Y%m%d")
    data_version = f"{version_date}-{now:%H%M}"
    return {
        "run_id": str(run_id),
        "generated_at": now.isoformat(),
        "latest_trade_date": latest,
        "data_version": data_version,
        "source_pipeline": "update_all_site_data",
    }


def annotate_json_file(path: Path, metadata: dict[str, str]) -> None:
    payload = read_json(path, None)
    if not isinstance(payload, dict):
        return
    changed = False
    for key, value in metadata.items():
        if payload.get(key) != value:
            payload[key] = value
            changed = True
    if changed:
        write_json(path, payload)


def remove_false_unified_news_metadata() -> None:
    """Undo metadata-only news refreshes left by older unified runs.

    There is no news-source step in ``STEPS``.  The existing event content must
    therefore keep its own ``updated_at`` / ``published_at`` dates instead of
    inheriting the current market-data run id and trade date.
    """
    for path in (DATA_PROCESSED / NEWS_EVENTS_NAME, DOCS_PROCESSED / NEWS_EVENTS_NAME):
        payload = read_json(path, None)
        if not isinstance(payload, dict) or payload.get("source_pipeline") != "update_all_site_data":
            continue
        changed = False
        for key in COMMON_KEYS:
            if key in payload:
                del payload[key]
                changed = True
        if changed:
            write_json(path, payload)


def annotate_outputs(metadata: dict[str, str], excluded_names: set[str] | None = None) -> None:
    # News carries its own official disclosure snapshot and publication dates;
    # never replace them with the market close date from this wrapper.
    excluded = {NEWS_EVENTS_NAME} | (excluded_names or set())
    canonical_processed = [DATA_PROCESSED / path.name for path in STATUS_TARGETS if path.parent == DOCS_PROCESSED]
    for path in canonical_processed + STATUS_TARGETS + [ROOT_UPDATE_STATUS, ROOT_UPDATE_LOG]:
        if path.name not in excluded:
            annotate_json_file(path, metadata)


def news_content_date(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    values = [
        normalize_date(first_existing(payload, ("content_latest_at", "last_fetched_at", "updated_at")))
    ]
    for item in get_items(payload):
        if isinstance(item, dict):
            values.append(
                normalize_date(
                    first_existing(item, ("published_at", "publishedAt", "event_date", "date"))
                )
            )
    return max((value for value in values if value), default="")


def file_status(path: Path, expected_latest: str) -> dict[str, Any]:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    payload = read_json(path, {})
    exists = path.exists()
    items = get_items(payload)
    is_news = path.name == NEWS_EVENTS_NAME
    has_live_news_source = bool(
        is_news
        and isinstance(payload, dict)
        and payload.get("source_pipeline") == "update_news_events"
        and payload.get("ok") is True
    )
    is_unfetched_news = is_news and not has_live_news_source
    date = news_content_date(payload) if is_news else payload_date(payload)
    updated_at = first_existing(payload, ("generated_at", "updated_at", "last_updated", "unified_update_at")) or ""
    count = payload_count(payload)
    failed_reasons: list[str] = []

    if isinstance(payload, dict):
        for key in ("failed_reasons", "errors", "warnings", "warning"):
            value = payload.get(key)
            if isinstance(value, list):
                failed_reasons.extend(str(item) for item in value if item)
            elif value:
                failed_reasons.append(str(value))
        if payload.get("message") and str(payload.get("status", "")).lower() in {"failed", "error", "partial_failed"}:
            failed_reasons.append(str(payload["message"]))

    ok_value = payload.get("ok") if isinstance(payload, dict) else None
    status_value = str(payload.get("status", "")).lower() if isinstance(payload, dict) else ""
    previous_preserved = bool(payload.get("previous_data_preserved")) if isinstance(payload, dict) else False

    status = "ok"
    if not exists:
        status = "missing"
        failed_reasons.append("file missing")
    elif ok_value is False or status_value in {"failed", "error", "partial_failed"}:
        status = "failed"
    elif payload.get("stale") if isinstance(payload, dict) else False:
        status = "stale"
    elif is_unfetched_news:
        status = "unavailable"
        detail = f"; existing content latest at {date}" if date else ""
        failed_reasons.append(
            "no news-source refresh step ran; existing news content was preserved" + detail
        )
    elif expected_latest and date and date != expected_latest and rel in CRITICAL_SYNC_FILES:
        status = "stale"
        failed_reasons.append(f"content date {date} != site latest_trade_date {expected_latest}")

    if previous_preserved and status == "ok":
        status = "stale"
        failed_reasons.append("previous data preserved after failed refresh")

    return {
        "file": rel,
        "exists": exists,
        "status": status,
        "generated_at": payload.get("generated_at", "") if isinstance(payload, dict) else "",
        "updated_at": updated_at,
        "latest_trade_date": date,
        "content_latest_at": date,
        "rows": count,
        "items_count": count,
        "previous_data_preserved": previous_preserved,
        "failed_reasons": failed_reasons,
    }


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


def freshness_warnings(latest: str, now: datetime) -> list[str]:
    if not latest:
        return ["Unable to determine latest trade date."]
    try:
        latest_dt = datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=TAIPEI)
    except ValueError:
        return [f"Invalid latest_trade_date: {latest}"]
    lag = business_days_between(latest_dt, now)
    if now.time() < time(15, 20) and lag <= 1:
        return ["Before Taipei 15:20 close-data refresh window; previous trading day is acceptable."]
    if lag > 1:
        return [f"Data is behind: latest trade date {latest}; Taipei now {now:%Y-%m-%d %H:%M}."]
    return []


def build_unified_status(metadata: dict[str, str], step_results: list[dict[str, Any]]) -> dict[str, Any]:
    latest = metadata["latest_trade_date"]
    files = [file_status(path, latest) for path in STATUS_TARGETS]
    stale_files = [item["file"] for item in files if item["status"] == "stale"]
    unavailable_files = [item["file"] for item in files if item["status"] == "unavailable"]
    failed_reasons: list[str] = [
        f"{step['name']}: {step['error']}"
        for step in step_results
        if not step["ok"] and step.get("error")
    ]
    for item in files:
        if item["status"] in {"failed", "missing", "stale"}:
            failed_reasons.extend(f"{item['file']}: {reason}" for reason in item["failed_reasons"])

    warnings = freshness_warnings(latest, datetime.fromisoformat(metadata["generated_at"]))
    warnings.extend(
        f"{item['file']}: {'; '.join(item['failed_reasons'])}"
        for item in files
        if item["status"] == "unavailable"
    )
    status = "ok"
    if failed_reasons:
        status = "failed"
    elif stale_files or warnings:
        status = "stale" if stale_files else "warning"

    payload = {
        **metadata,
        "status": status,
        # A pre-close freshness warning is informational: the refresh itself
        # completed and the previous trading day is the expected baseline.
        "ok": status in {"ok", "warning"},
        "each_file_status": files,
        "files": files,
        "stale_files": sorted(set(stale_files)),
        "unavailable_files": sorted(set(unavailable_files)),
        "failed_reasons": failed_reasons,
        "warning": warnings,
        "source_status": step_results,
        "items": [
            {
                "file": item["file"],
                "generated_at": item["generated_at"],
                "updated_at": item["updated_at"],
                "latest_trade_date": item["latest_trade_date"],
                "rows": item["rows"],
                "status": item["status"],
                "error": "; ".join(item["failed_reasons"]),
            }
            for item in files
        ],
    }
    return payload


def write_status_files(status: dict[str, Any]) -> None:
    write_json(DATA_STATUS, status)
    site_meta_payload = {
        key: status[key]
        for key in ("run_id", "generated_at", "latest_trade_date", "data_version", "source_pipeline", "status", "ok")
        if key in status
    } | {
        "stale_files": status.get("stale_files", []),
        "failed_reasons": status.get("failed_reasons", []),
    }
    write_json(SITE_META, site_meta_payload)
    write_json(ROOT_DATA_STATUS, status)
    write_json(ROOT_SITE_META, site_meta_payload)
    write_json(ROOT_UPDATE_LOG, status)
    write_json(DOCS_UPDATE_LOG, status)

    update_status = read_json(DOCS_UPDATE_STATUS, {})
    if not isinstance(update_status, dict):
        update_status = {}
    update_status.update(status)
    update_status["trade_date"] = status.get("latest_trade_date") or update_status.get("trade_date")
    write_json(DOCS_UPDATE_STATUS, update_status)
    write_json(ROOT_UPDATE_STATUS, update_status)


def write_validation_failure_status(reason: str, previous: dict[str, Any]) -> None:
    """Preserve prior validation data while exposing this run's real failure."""
    if not isinstance(previous, dict):
        previous = {}
    generated_at = now_taipei().isoformat()
    payload = {
        **{
            key: previous.get(key)
            for key in (
                "latestSignalDate",
                "latestEntryDate",
                "latestPriceDate",
                "latestBenchmarkDate",
                "completedSignals",
                "trackingSignals",
                "d20CompletedSignals",
                "missingPriceCount",
                "missingBenchmarkCount",
                "validationVersion",
                "latest_trade_date",
            )
        },
        "status": "failed",
        "ok": False,
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latestValidationUpdateTime": generated_at,
        "pipelineIntegrated": True,
        "previousDataPreserved": True,
        "lastError": reason,
        "failedReasons": [reason],
        "warnings": previous.get("warnings") or [],
    }
    write_json(DATA_PROCESSED / AI_VALIDATION_STATUS_NAME, payload)
    write_json(DOCS_PROCESSED / AI_VALIDATION_STATUS_NAME, payload)


def main() -> int:
    factor_snapshot = snapshot_files(FACTOR_OUTPUTS)
    factor_history_snapshot = snapshot_directory(FACTOR_TOP10_HISTORY)
    validation_snapshot = snapshot_files(AI_VALIDATION_OUTPUTS)
    validation_history_snapshot = snapshot_directory(AI_VALIDATION_HISTORY)
    validation_previous_status = read_json(
        DATA_PROCESSED / AI_VALIDATION_STATUS_NAME,
        {},
    )
    factor_pipeline_failed = False
    validation_pipeline_failed = False
    step_results: list[dict[str, Any]] = []
    for name, script in STEPS:
        if name in {"ai_validation", "validate_ai_validation"} and factor_pipeline_failed:
            result = {
                "name": name,
                "script": script,
                "ok": False,
                "returncode": None,
                "started_at": now_taipei().isoformat(),
                "finished_at": now_taipei().isoformat(),
                "stdout_tail": "",
                "stderr_tail": "",
                "error": "dependency failed: official factor/Top 10 pipeline did not complete",
            }
        elif name == "validate_ai_validation" and validation_pipeline_failed:
            result = {
                "name": name,
                "script": script,
                "ok": False,
                "returncode": None,
                "started_at": now_taipei().isoformat(),
                "finished_at": now_taipei().isoformat(),
                "stdout_tail": "",
                "stderr_tail": "",
                "error": "dependency failed: AI validation generator did not complete",
            }
        else:
            result = run_step(name, script)
        step_results.append(result)
        if name in {"factor_scores", "validate_factor_scores"} and not result["ok"]:
            factor_pipeline_failed = True
            # update_factor_scores is expected to preserve old data itself, but
            # The wrapper also rolls back every canonical factor/persistence
            # output in case a process failed between writes.
            restore_files(factor_snapshot)
            restore_directory(FACTOR_TOP10_HISTORY, factor_history_snapshot)
        if name in {"ai_validation", "validate_ai_validation"} and not result["ok"]:
            if not validation_pipeline_failed:
                validation_pipeline_failed = True
                restore_files(validation_snapshot)
                restore_directory(AI_VALIDATION_HISTORY, validation_history_snapshot)
                write_validation_failure_status(
                    f"{name}: {result.get('error') or 'unknown validation failure'}",
                    validation_previous_status,
                )

    now = now_taipei()
    latest = latest_trade_date()
    metadata = make_metadata(now, latest)

    # factor-scores.json and all Top 10 persistence outputs have one official
    # source only: scripts/update_factor_scores.py. No AI-score fallback runs.

    remove_false_unified_news_metadata()
    excluded_names = FACTOR_OUTPUT_NAMES if factor_pipeline_failed else set()
    if validation_pipeline_failed:
        excluded_names |= AI_VALIDATION_OUTPUT_NAMES | {AI_VALIDATION_STATUS_NAME}
    annotate_outputs(metadata, excluded_names)
    sync_processed_to_docs()
    copy_status_sidecars()

    latest = latest_trade_date()
    if latest != metadata["latest_trade_date"]:
        metadata = make_metadata(now, latest)
    annotate_outputs(metadata, excluded_names)

    unified_status = build_unified_status(metadata, step_results)
    write_status_files(unified_status)

    print(f"Update All Site Data: {unified_status['status']}")
    print(f"generated_at: {unified_status['generated_at']}")
    print(f"latest_trade_date: {unified_status.get('latest_trade_date') or '--'}")
    if unified_status.get("stale_files"):
        print("stale_files:")
        for item in unified_status["stale_files"]:
            print(f"- {item}")
    if unified_status.get("failed_reasons"):
        print("failed_reasons:")
        for reason in unified_status["failed_reasons"]:
            print(f"- {reason}")
    return 1 if unified_status["status"] in {"failed", "stale"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
