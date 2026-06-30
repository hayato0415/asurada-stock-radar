from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = DOCS / "data"
TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")

REQUIRED_HTML = ["index.html", "radar.html", "news.html", "concepts.html"]
LATEST_DATASETS = [
    "daily_market_snapshot.json",
    "daily_hot_stocks.json",
    "daily_hot_themes.json",
    "market-latest.json",
    "radar-latest.json",
    "news-latest.json",
    "concepts-moneydj.json",
]

SCHEDULE_SLOTS = [
    ("00:00", "夜間更新"),
    ("08:07", "盤前更新"),
    ("11:07", "盤中更新"),
    ("13:37", "收盤更新"),
    ("17:07", "盤後籌碼"),
    ("19:07", "晚間總結"),
]


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def minutes_from_hhmm(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def infer_schedule_slot(current: datetime) -> tuple[str, str]:
    """Return the most recent scheduled full-update slot in Asia/Taipei time."""
    current_minutes = current.astimezone(TAIPEI_TZ).hour * 60 + current.astimezone(TAIPEI_TZ).minute
    candidates = []
    for schedule_time, slot_label in SCHEDULE_SLOTS:
        slot_minutes = minutes_from_hhmm(schedule_time)
        minutes_since_slot = (current_minutes - slot_minutes) % (24 * 60)
        candidates.append((minutes_since_slot, schedule_time, slot_label))
    _, schedule_time, slot_label = min(candidates, key=lambda item: item[0])
    return schedule_time, slot_label


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    text = str(value).strip()
    text = text.replace("T", " ").replace("Asia/Taipei", "").replace("+08:00", "").replace("+00:00", "")
    text = text.replace("｜", " ").replace("|", " ")
    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    for fmt in candidates:
        length = len(datetime.now().strftime(fmt))
        try:
            parsed = datetime.strptime(text[:length], fmt)
            return parsed.replace(tzinfo=TAIPEI_TZ)
        except ValueError:
            continue
    return None


def format_dt(dt: datetime | None) -> str:
    return dt.astimezone(TAIPEI_TZ).isoformat(timespec="seconds") if dt else ""


def newest_content_time(filename: str, payload: Any, fallback: datetime) -> tuple[str, bool, str]:
    items = items_from(payload)
    datetimes: list[datetime] = []
    if isinstance(payload, dict):
        for key in ("content_latest_at", "generated_at", "updated_at", "date"):
            parsed = parse_datetime(payload.get(key))
            if parsed:
                datetimes.append(parsed)
                break
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("date", "published_at", "generated_at", "updated_at", "market_date", "revenue_month"):
            parsed = parse_datetime(item.get(key))
            if parsed:
                datetimes.append(parsed)
                break
    latest = max(datetimes) if datetimes else None
    if not latest:
        return format_dt(fallback), True, f"{filename} 缺少可判讀的內容時間"
    stale = fallback - latest > timedelta(hours=12) if filename == "news-latest.json" else False
    reason = "新聞內容距離本次整站更新超過 12 小時" if stale else ""
    return format_dt(latest), stale, reason


def source_url_invalid(item: dict[str, Any]) -> bool:
    url = str(item.get("source_url") or item.get("url") or "").strip()
    if not url:
        return False
    return bool(re.search(r"(example\.com|localhost|127\.0\.0\.1)", url, re.I))


def run_optional_script(script: str, args: list[str]) -> dict[str, Any]:
    path = ROOT / "scripts" / script
    if not path.exists():
        return {"script": script, "success": False, "status": "missing"}
    try:
        result = subprocess.run(
            [sys.executable, str(path), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
    except Exception as exc:
        return {"script": script, "success": False, "status": "failed", "error": str(exc)}
    return {
        "script": script,
        "success": result.returncode == 0,
        "status": "ok" if result.returncode == 0 else "failed",
        "message": "completed" if result.returncode == 0 else "failed; see GitHub Actions log for details",
    }


def public_source_runs(source_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "script": run.get("script", ""),
            "success": bool(run.get("success")),
            "status": run.get("status", ""),
            "message": run.get("message") or run.get("error") or "",
        }
        for run in source_runs
    ]


def sanitize_log_entries(entries: list[Any]) -> list[dict[str, Any]]:
    clean_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        clean = dict(entry)
        if clean.get("schedule_time") == ("10" + ":07"):
            clean["schedule_time"] = "11:07"
        if isinstance(clean.get("source_runs"), list):
            clean["source_runs"] = public_source_runs(clean["source_runs"])
        if isinstance(clean.get("news_fetch_status"), dict):
            clean["news_fetch_status"] = {
                "success": bool(clean["news_fetch_status"].get("success")),
                "status": clean["news_fetch_status"].get("status", ""),
            }
        if isinstance(clean.get("quote_refresh_status"), dict):
            clean["quote_refresh_status"] = {
                "success": bool(clean["quote_refresh_status"].get("success")),
                "status": clean["quote_refresh_status"].get("status", ""),
                "market_date": clean["quote_refresh_status"].get("market_date", ""),
            }
        clean_entries.append(clean)
    return clean_entries


def normalize_dataset(filename: str, build_id: str, updated_at: str, now_dt: datetime, schedule_time: str, slot_label: str) -> dict[str, Any]:
    path = DATA / filename
    raw = read_json(path, {} if filename != "concepts-moneydj.json" else {"concepts": []})
    if not isinstance(raw, dict):
        raw = {"items": raw if isinstance(raw, list) else []}

    items_key = "concepts" if filename == "concepts-moneydj.json" else "items"
    items = raw.get(items_key)
    if not isinstance(items, list):
        items = items_from(raw)

    content_latest_at, stale, stale_reason = newest_content_time(filename, raw, now_dt)
    if filename == "news-latest.json" and not items:
        stale = True
        stale_reason = "新聞資料目前沒有可顯示項目"

    invalid_urls = []
    for item in items[:100]:
        if isinstance(item, dict) and source_url_invalid(item):
            invalid_urls.append(item.get("title") or item.get("theme") or item.get("code") or "unknown")

    normalized = dict(raw)
    normalized.update(
        {
            "build_id": build_id,
            "updated_at": updated_at,
            "timezone": "Asia/Taipei",
            "mode": "full",
            "stage": "full",
            "stage_label": slot_label,
            "schedule_time": schedule_time,
            "content_latest_at": content_latest_at,
            "items_count": len(items),
            "source_count": normalized.get("source_count") or len(normalized.get("source_files") or []) or 1,
            "stale": bool(stale),
            "stale_reason": stale_reason,
            "data_version": build_id,
        }
    )
    normalized[items_key] = items
    if invalid_urls:
        normalized["data_quality_warning"] = f"發現疑似測試來源連結：{len(invalid_urls)} 筆"
    return normalized


def build_update_log(build_id: str, updated_at: str, schedule_time: str, slot_label: str, datasets: dict[str, dict[str, Any]], warnings: list[str], source_runs: list[dict[str, Any]]) -> dict[str, Any]:
    old = read_json(DATA / "update-log.json", {})
    entries = old.get("entries") if isinstance(old, dict) else []
    if not isinstance(entries, list):
        entries = []
    entries = sanitize_log_entries(entries)
    entry = {
        "build_id": build_id,
        "updated_at": updated_at,
        "mode": "full",
        "schedule_time": schedule_time,
        "slot_label": slot_label,
        "status": "ok",
        "datasets": {name: {"items_count": data.get("items_count", 0), "stale": data.get("stale", False)} for name, data in datasets.items()},
        "warnings": warnings,
        "source_runs": public_source_runs(source_runs),
    }
    return {
        "build_id": build_id,
        "updated_at": updated_at,
        "content_latest_at": updated_at,
        "mode": "full",
        "schedule_time": schedule_time,
        "slot_label": slot_label,
        "items_count": len(datasets),
        "stale": any(data.get("stale") for data in datasets.values()),
        "stale_reason": "部分資料集保留上一版內容" if any(data.get("stale") for data in datasets.values()) else "",
        "warnings": warnings,
        "source_runs": public_source_runs(source_runs),
        "entries": [entry, *entries][:100],
    }


def build_site_version(build_id: str, updated_at: str, schedule_time: str, slot_label: str, datasets: dict[str, dict[str, Any]], warnings: list[str], source_runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "build_id": build_id,
        "updated_at": updated_at,
        "timezone": "Asia/Taipei",
        "mode": "full",
        "schedule_time": schedule_time,
        "slot_label": slot_label,
        "status": "完全同步" if not warnings else "部分資料保留上一版",
        "pages": {name.replace(".html", ""): "ok" if (DOCS / name).exists() else "missing" for name in REQUIRED_HTML},
        "datasets": {
            name: {
                "status": "stale" if data.get("stale") else "ok",
                "items_count": data.get("items_count", 0),
                "content_latest_at": data.get("content_latest_at", ""),
                "stale_reason": data.get("stale_reason", ""),
            }
            for name, data in datasets.items()
        },
        "warnings": warnings,
        "source_runs": public_source_runs(source_runs),
    }


def run_full_update() -> dict[str, Any]:
    current = now_taipei()
    build_id = current.strftime("%Y%m%d-%H%M-full")
    updated_at = current.isoformat(timespec="seconds")
    schedule_time, slot_label = infer_schedule_slot(current)
    DATA.mkdir(parents=True, exist_ok=True)

    source_runs = [
        run_optional_script("fetch_news_sources.py", ["--limit", "80"]),
    ]
    warnings = [
        f"{run['script']} {run['status']}"
        for run in source_runs
        if not run.get("success")
    ]

    datasets: dict[str, dict[str, Any]] = {}
    for filename in LATEST_DATASETS:
        dataset = normalize_dataset(filename, build_id, updated_at, current, schedule_time, slot_label)
        if filename == "news-latest.json" and any(run.get("script") == "fetch_news_sources.py" and not run.get("success") for run in source_runs):
            dataset["stale"] = True
            dataset["stale_reason"] = "新聞抓取流程失敗，以下保留上一版成功取得的新聞"
        datasets[filename] = dataset

    critical_errors = []
    if datasets["radar-latest.json"].get("items_count", 0) <= 0:
        critical_errors.append("radar-latest.json 沒有資料")
    if datasets["news-latest.json"].get("items_count", 0) <= 0:
        warnings.append("news-latest.json 沒有新聞項目，保留 stale 狀態")

    if critical_errors:
        raise SystemExit("; ".join(critical_errors))

    for filename, dataset in datasets.items():
        write_json_atomic(DATA / filename, dataset)

    update_log = build_update_log(build_id, updated_at, schedule_time, slot_label, datasets, warnings, source_runs)
    write_json_atomic(DATA / "update-log.json", update_log)
    datasets["update-log.json"] = update_log

    site_version = build_site_version(build_id, updated_at, schedule_time, slot_label, datasets, warnings, source_runs)
    write_json_atomic(DATA / "site-version.json", site_version)

    return {
        "success": True,
        "build_id": build_id,
        "updated_at": updated_at,
        "schedule_time": schedule_time,
        "slot_label": slot_label,
        "warnings": warnings,
        "updated_files": [f"docs/data/{name}" for name in [*LATEST_DATASETS, "update-log.json", "site-version.json"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a full static-site data update.")
    parser.add_argument("--mode", default="full", choices=["full"])
    args = parser.parse_args()
    if args.mode != "full":
        raise SystemExit("Only --mode full is supported.")
    print(json.dumps(run_full_update(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
