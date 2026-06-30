#!/usr/bin/env python3
"""Full-site data update entrypoint.

This script is intentionally stricter than the older normalizer:
it first runs the real data builders, then normalizes every public
latest JSON with one build id. If content timestamps are still old,
the dataset is marked stale instead of pretending the update succeeded.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
DATA = ROOT / "data"
SCRIPTS = ROOT / "scripts"

try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")

LATEST_DATASETS = [
    "daily_market_snapshot.json",
    "daily_hot_stocks.json",
    "daily_hot_themes.json",
    "market-latest.json",
    "radar-latest.json",
    "news-latest.json",
    "concepts-moneydj.json",
]

CRITICAL_DATASETS = {
    "radar-latest.json",
    "news-latest.json",
    "concepts-moneydj.json",
}

STALE_THRESHOLDS = {
    "news-latest.json": timedelta(hours=12),
    "market-latest.json": timedelta(days=4),
    "radar-latest.json": timedelta(days=4),
    "daily_market_snapshot.json": timedelta(days=4),
    "daily_hot_stocks.json": timedelta(days=4),
    "daily_hot_themes.json": timedelta(days=4),
    "concepts-moneydj.json": timedelta(days=14),
}

SCHEDULE_SLOTS = [
    ("00:00", "夜間更新"),
    ("08:07", "盤前更新"),
    ("11:07", "盤中更新"),
    ("13:37", "收盤更新"),
    ("17:07", "盤後籌碼"),
    ("19:07", "晚間總結"),
]

PIPELINE_STEPS = [
    ("market_snapshot", "fetch_market_snapshot.py", [], 180),
    ("daily_evening_initial", "update_daily.py", ["--stage", "evening"], 360),
    ("news_sources", "fetch_news_sources.py", ["--limit", "80"], 300),
    ("radar_rankings", "build_radar_rankings.py", [], 180),
    ("moneydj_crawl", "crawl_moneydj_concepts.py", [], 900),
    ("moneydj_json", "build_moneydj_concepts_json.py", [], 180),
    ("stock_concept_index", "build_stock_concept_index.py", [], 180),
    # Rebuild the public latest files after source refreshes.
    ("daily_evening_final", "update_daily.py", ["--stage", "evening"], 360),
]


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(microsecond=0)


def iso_taipei(dt: datetime) -> str:
    return dt.astimezone(TAIPEI).replace(microsecond=0).isoformat()


def display_taipei(dt: datetime) -> str:
    return dt.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


def current_schedule_slot(dt: datetime) -> dict[str, str]:
    local = dt.astimezone(TAIPEI)
    minutes = local.hour * 60 + local.minute
    slots = []
    for schedule_time, label in SCHEDULE_SLOTS:
        hour, minute = [int(part) for part in schedule_time.split(":")]
        slot_minutes = hour * 60 + minute
        slots.append((slot_minutes, schedule_time, label))
    selected = slots[0]
    for slot in slots:
        if minutes >= slot[0]:
            selected = slot
    if minutes < slots[0][0]:
        selected = slots[-1]
    return {"schedule_time": selected[1], "slot_label": selected[2]}


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


def read_json(path: Path, fallback: Any = None) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def copy_to_data(filename: str, payload: Any) -> None:
    write_json_atomic(DATA / filename, payload)


def run_script(label: str, script_name: str, args: list[str], timeout: int) -> dict[str, Any]:
    script_path = SCRIPTS / script_name
    if not script_path.exists():
        return {
            "label": label,
            "script": script_name,
            "success": False,
            "returncode": None,
            "error": f"{script_name} 不存在",
        }

    command = [sys.executable, str(script_path), *args]
    started_at = now_taipei()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "label": label,
            "script": script_name,
            "args": args,
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "started_at": display_taipei(started_at),
            "finished_at": display_taipei(now_taipei()),
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "script": script_name,
            "args": args,
            "success": False,
            "returncode": None,
            "started_at": display_taipei(started_at),
            "finished_at": display_taipei(now_taipei()),
            "error": f"{script_name} 執行逾時 {timeout} 秒",
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }


def add_dt(values: list[datetime], value: Any) -> None:
    parsed = parse_datetime(value)
    if parsed:
        values.append(parsed)


def content_datetimes(filename: str, payload: Any) -> list[datetime]:
    values: list[datetime] = []
    if not isinstance(payload, dict):
        return values

    items = payload.get("items")
    if not isinstance(items, list):
        concepts = payload.get("concepts")
        items = concepts if isinstance(concepts, list) else []

    if filename == "market-latest.json":
        snapshot = payload.get("snapshot")
        if isinstance(snapshot, dict):
            add_dt(values, snapshot.get("market_date"))
            add_dt(values, snapshot.get("date"))
        add_dt(values, payload.get("content_latest_at"))
        add_dt(values, payload.get("market_date"))
        add_dt(values, payload.get("date"))
    elif filename == "daily_market_snapshot.json":
        add_dt(values, payload.get("market_date"))
        add_dt(values, payload.get("date"))
        snapshot = payload.get("snapshot")
        if isinstance(snapshot, dict):
            add_dt(values, snapshot.get("market_date"))
            add_dt(values, snapshot.get("date"))
    elif filename == "radar-latest.json":
        for item in items:
            if isinstance(item, dict):
                for key in ("market_date", "quote_date", "date", "updated_at"):
                    add_dt(values, item.get(key))
        add_dt(values, payload.get("content_latest_at"))
        add_dt(values, payload.get("market_date"))
        add_dt(values, payload.get("date"))
    elif filename in {"daily_hot_stocks.json", "daily_hot_themes.json"}:
        for item in items:
            if isinstance(item, dict):
                for key in ("market_date", "quote_date", "date", "updated_at", "generated_at"):
                    add_dt(values, item.get(key))
        add_dt(values, payload.get("content_latest_at"))
        add_dt(values, payload.get("date"))
    elif filename == "news-latest.json":
        for item in items:
            if isinstance(item, dict):
                for key in ("date", "published_at", "published_time", "time", "updated_at"):
                    add_dt(values, item.get(key))
        add_dt(values, payload.get("content_latest_at"))
    elif filename == "concepts-moneydj.json":
        add_dt(values, payload.get("content_latest_at"))
        add_dt(values, payload.get("generated_at"))
        add_dt(values, payload.get("updated_at"))
        for item in items:
            if isinstance(item, dict):
                add_dt(values, item.get("updated_at"))
    else:
        add_dt(values, payload.get("content_latest_at"))
        add_dt(values, payload.get("generated_at"))
        add_dt(values, payload.get("updated_at"))
        add_dt(values, payload.get("date"))

    return values


def item_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    items = payload.get("items")
    if isinstance(items, list):
        return len(items)
    concepts = payload.get("concepts")
    if isinstance(concepts, list):
        return len(concepts)
    return 0


def source_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    if isinstance(payload.get("source_count"), int):
        return payload["source_count"]
    sources = payload.get("sources")
    if isinstance(sources, list):
        return len(sources)
    items = payload.get("items")
    if isinstance(items, list):
        names = {
            str(item.get("source") or item.get("source_name") or "").strip()
            for item in items
            if isinstance(item, dict)
        }
        return len([name for name in names if name])
    if payload.get("source"):
        return 1
    return 0


def normalize_dataset(
    filename: str,
    build_id: str,
    updated_at: datetime,
    schedule: dict[str, str],
    stale_reason: str = "",
) -> dict[str, Any]:
    path = DOCS_DATA / filename
    raw = read_json(path, {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raw = {"items": raw if isinstance(raw, list) else [], "raw_value": raw}

    count = item_count(raw)
    dates = content_datetimes(filename, raw)
    latest = max(dates) if dates else None
    content_latest_at = iso_taipei(latest) if latest else ""

    reasons: list[str] = []
    if stale_reason:
        reasons.append(stale_reason)
    if not latest:
        reasons.append("無法判斷內容資料時間")
    else:
        threshold = STALE_THRESHOLDS.get(filename)
        if threshold and updated_at.astimezone(TAIPEI) - latest > threshold:
            reasons.append(
                f"內容最新時間 {display_taipei(latest)} 與全站更新時間相差超過 {threshold}"
            )

    if filename in CRITICAL_DATASETS and count == 0:
        reasons.append("必要資料筆數為 0")

    payload = dict(raw)
    payload.update(
        {
            "updated_at": display_taipei(updated_at),
            "build_id": build_id,
            "data_version": build_id,
            "stage": "full",
            "stage_label": schedule["slot_label"],
            "schedule_time": schedule["schedule_time"],
            "timezone": "Asia/Taipei",
            "source_count": source_count(payload),
            "items_count": count,
            "content_latest_at": content_latest_at,
            "stale": bool(reasons),
            "stale_reason": "；".join(reasons),
        }
    )
    return payload


def stale_overrides_from_runs(runs: list[dict[str, Any]]) -> dict[str, str]:
    reasons: dict[str, list[str]] = {}

    def mark(files: list[str], reason: str) -> None:
        for file in files:
            reasons.setdefault(file, []).append(reason)

    by_label = {run["label"]: run for run in runs}

    if not by_label.get("market_snapshot", {}).get("success"):
        mark(["daily_market_snapshot.json", "market-latest.json"], "盤勢資料抓取失敗，保留上一版")
    if not by_label.get("news_sources", {}).get("success"):
        mark(["news-latest.json"], "新聞來源抓取失敗，保留上一版")
    if not by_label.get("radar_rankings", {}).get("success"):
        mark(["daily_hot_themes.json", "daily_hot_stocks.json"], "題材排行重建失敗，保留上一版")
    if not by_label.get("moneydj_crawl", {}).get("success") or not by_label.get("moneydj_json", {}).get("success"):
        mark(["concepts-moneydj.json"], "MoneyDJ 概念股更新失敗，保留上一版")

    daily_failed = [
        run for run in runs if run["script"] == "update_daily.py" and not run.get("success")
    ]
    if daily_failed:
        mark(
            [
                "market-latest.json",
                "radar-latest.json",
                "news-latest.json",
                "daily_hot_stocks.json",
                "daily_hot_themes.json",
            ],
            "daily latest 重建失敗，保留上一版",
        )

    return {file: "；".join(parts) for file, parts in reasons.items()}


def dataset_summary(filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = "stale" if payload.get("stale") else "ok"
    if filename in CRITICAL_DATASETS and payload.get("items_count", 0) == 0:
        status = "failed"
    return {
        "file": filename,
        "status": status,
        "updated_at": payload.get("updated_at", ""),
        "content_latest_at": payload.get("content_latest_at", ""),
        "items_count": payload.get("items_count", 0),
        "source_count": payload.get("source_count", 0),
        "stale": bool(payload.get("stale")),
        "stale_reason": payload.get("stale_reason", ""),
    }


def run_validation() -> None:
    command = [sys.executable, str(SCRIPTS / "validate_site_build.py")]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)


def run_full_update(mode: str = "full") -> dict[str, Any]:
    updated_at = now_taipei()
    schedule = current_schedule_slot(updated_at)
    build_id = updated_at.strftime("%Y%m%d-%H%M-full")

    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    source_runs: list[dict[str, Any]] = []
    for label, script, args, timeout in PIPELINE_STEPS:
        run = run_script(label, script, args, timeout)
        source_runs.append(run)
        status = "OK" if run.get("success") else "STALE"
        print(f"[{status}] {label}: {script} {' '.join(args)}")

    stale_overrides = stale_overrides_from_runs(source_runs)
    dataset_payloads: dict[str, dict[str, Any]] = {}
    summaries: list[dict[str, Any]] = []

    for filename in LATEST_DATASETS:
        payload = normalize_dataset(
            filename,
            build_id,
            updated_at,
            schedule,
            stale_overrides.get(filename, ""),
        )
        dataset_payloads[filename] = payload
        summaries.append(dataset_summary(filename, payload))
        write_json_atomic(DOCS_DATA / filename, payload)
        copy_to_data(filename, payload)

    stale_files = [summary["file"] for summary in summaries if summary["status"] == "stale"]
    failed_files = [summary["file"] for summary in summaries if summary["status"] == "failed"]

    success = not failed_files
    site_status = "完全同步" if success and not stale_files else "部分資料保留上一版"

    update_log = {
        "build_id": build_id,
        "updated_at": display_taipei(updated_at),
        "timezone": "Asia/Taipei",
        "mode": mode,
        "schedule_time": schedule["schedule_time"],
        "slot_label": schedule["slot_label"],
        "success": success,
        "status": site_status,
        "datasets": summaries,
        "source_runs": source_runs,
        "warnings": [f"{file} stale" for file in stale_files],
        "errors": [f"{file} failed" for file in failed_files],
    }

    site_version = {
        "build_id": build_id,
        "updated_at": display_taipei(updated_at),
        "timezone": "Asia/Taipei",
        "mode": mode,
        "schedule_time": schedule["schedule_time"],
        "slot_label": schedule["slot_label"],
        "status": site_status,
        "success": success,
        "datasets": summaries,
        "stale_files": stale_files,
        "failed_files": failed_files,
    }

    write_json_atomic(DOCS_DATA / "update-log.json", update_log)
    write_json_atomic(DOCS_DATA / "site-version.json", site_version)
    copy_to_data("update-log.json", update_log)
    copy_to_data("site-version.json", site_version)

    run_validation()
    print(f"Full site update complete: {build_id} ({site_status})")
    return site_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full asurada-stock-radar data update.")
    parser.add_argument("--mode", default="full", choices=["full"])
    args = parser.parse_args()
    run_full_update(args.mode)


if __name__ == "__main__":
    main()
