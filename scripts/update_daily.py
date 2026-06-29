from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
ARCHIVE_DIR = DOCS_DATA / "archive"
TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")
NEWS_FETCH_STATUS: dict = {}

STAGES = {
    "premarket": {
        "label": "盤前更新",
        "schedule_time": "08:07",
        "targets": ["market", "news"],
    },
    "intraday": {
        "label": "盤中更新",
        "schedule_time": "10:07",
        "targets": ["market", "themes", "news", "radar"],
    },
    "close": {
        "label": "收盤快照",
        "schedule_time": "13:37",
        "targets": ["market", "news", "radar"],
    },
    "afterhours": {
        "label": "盤後更新",
        "schedule_time": "17:07",
        "targets": ["news", "themes", "radar"],
    },
    "evening": {
        "label": "晚間總結",
        "schedule_time": "19:07",
        "targets": ["market", "themes", "news", "radar"],
    },
}


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_items(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    return []


def parse_news_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("T", " ").replace("+08:00", "").replace("Asia/Taipei", "").strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
            if fmt == "%Y-%m-%d":
                parsed = parsed.replace(hour=0, minute=0)
            return parsed.replace(tzinfo=TAIPEI_TZ)
        except ValueError:
            continue
    return None


def event_datetime(event: dict) -> datetime | None:
    if not isinstance(event, dict):
        return None
    for key in ("date", "published_at", "created_at", "updated_at"):
        parsed = parse_news_datetime(str(event.get(key) or ""))
        if parsed:
            return parsed
    return None


def refresh_news_events() -> dict:
    script = ROOT / "scripts" / "fetch_news_sources.py"
    if not script.exists():
        return {
            "success": False,
            "status": "missing_fetcher",
            "error": "scripts/fetch_news_sources.py 不存在",
        }
    command = [sys.executable, str(script), "--limit", "80"]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception as exc:
        return {"success": False, "status": "fetch_failed", "error": str(exc)}

    stdout = (result.stdout or "").strip()
    parsed = {}
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = {"raw_stdout": stdout[-1000:]}

    if result.returncode != 0:
        return {
            **parsed,
            "success": False,
            "status": "fetch_failed",
            "error": (result.stderr or parsed.get("error") or "新聞抓取腳本執行失敗").strip(),
        }
    return {
        **parsed,
        "success": bool(parsed.get("success", True)),
        "status": "fetch_ok",
        "stderr": result.stderr.strip(),
    }


def stock_master_count() -> int:
    master = read_json(DOCS_DATA / "stock-master.json", {})
    return len(master) if isinstance(master, dict) else 0


def base_payload(stage: str, source_files: list[str], updated_at: str, data_version: str) -> dict:
    stage_info = STAGES[stage]
    return {
        "updated_at": updated_at,
        "stage": stage,
        "stage_label": stage_info["label"],
        "schedule_time": stage_info["schedule_time"],
        "timezone": "Asia/Taipei",
        "source_count": len(source_files),
        "source_files": source_files,
        "data_version": data_version,
    }


def build_market_latest(stage: str, updated_at: str, data_version: str) -> dict:
    source_files = ["daily_market_snapshot.json"]
    snapshot = read_json(DOCS_DATA / "daily_market_snapshot.json", {})
    payload = base_payload(stage, source_files, updated_at, data_version)
    if isinstance(snapshot, dict):
        payload.update({
            "date": snapshot.get("date") or snapshot.get("trade_date") or "",
            "snapshot": snapshot,
        })
    else:
        payload["snapshot"] = {}
    return payload


def build_themes_latest(stage: str, updated_at: str, data_version: str) -> dict:
    source_files = ["theme-top5.json", "daily_hot_themes.json"]
    theme_top5 = read_json(DOCS_DATA / "theme-top5.json", {})
    hot_themes = read_json(DOCS_DATA / "daily_hot_themes.json", {})
    items = as_items(theme_top5)
    payload = base_payload(stage, source_files, updated_at, data_version)
    payload.update({
        "date": theme_top5.get("date") if isinstance(theme_top5, dict) else "",
        "generated_at": theme_top5.get("generated_at") if isinstance(theme_top5, dict) else "",
        "items": items,
        "hot_themes_summary": hot_themes if isinstance(hot_themes, dict) else {},
        "source_count": len([name for name in source_files if (DOCS_DATA / name).exists()]),
    })
    return payload


def build_news_latest(stage: str, updated_at: str, data_version: str) -> dict:
    source_files = ["news-events.json"]
    news = read_json(DOCS_DATA / "news-events.json", [])
    items = as_items(news) if isinstance(news, dict) else (news if isinstance(news, list) else [])
    items = [item for item in items if isinstance(item, dict)]
    items.sort(key=lambda item: event_datetime(item) or datetime(1900, 1, 1, tzinfo=TAIPEI_TZ), reverse=True)
    visible_items = items[:80]
    latest_dt = next((event_datetime(item) for item in visible_items if event_datetime(item)), None)
    content_latest_at = latest_dt.strftime("%Y-%m-%d %H:%M") if latest_dt else ""
    updated_dt = parse_news_datetime(updated_at) or now_taipei()
    old_latest = read_json(DOCS_DATA / "news-latest.json", {})
    old_items = as_items(old_latest)
    old_urls = {
        str(item.get("source_url") or item.get("url") or "")
        for item in old_items
        if isinstance(item, dict)
    }
    new_items_count = len([
        item for item in visible_items
        if str(item.get("source_url") or item.get("url") or "") not in old_urls
    ])
    fetch_ok = NEWS_FETCH_STATUS.get("success", True)
    stale = False
    stale_reason = ""
    if not fetch_ok:
        stale = True
        stale_reason = f"新聞抓取失敗：{NEWS_FETCH_STATUS.get('error') or NEWS_FETCH_STATUS.get('status') or '未知錯誤'}"
    elif not latest_dt:
        stale = True
        stale_reason = "新聞內容沒有可判讀的來源時間"
    elif updated_dt - latest_dt > timedelta(hours=12):
        stale = True
        stale_reason = f"最新新聞時間 {content_latest_at} 距離本次整理時間超過 12 小時"
    source_count = len({
        str(item.get("source_name") or "")
        for item in visible_items
        if item.get("source_name")
    })
    payload = base_payload(stage, source_files, updated_at, data_version)
    payload.update({
        "content_latest_at": content_latest_at,
        "items_count": len(items),
        "new_items_count": new_items_count,
        "stale": stale,
        "stale_reason": stale_reason,
        "source_count": source_count,
        "news_fetch_status": NEWS_FETCH_STATUS,
        "items": visible_items,
        "total_available": len(items),
    })
    return payload


def build_radar_latest(stage: str, updated_at: str, data_version: str) -> dict:
    source_files = ["stocks-latest.json", "stock-data-meta.json", "stock-master.json"]
    stocks = read_json(DOCS_DATA / "stocks-latest.json", [])
    stock_meta = read_json(DOCS_DATA / "stock-data-meta.json", {})
    items = stocks if isinstance(stocks, list) else as_items(stocks)
    payload = base_payload(stage, source_files, updated_at, data_version)
    payload.update({
        "date": stock_meta.get("date") if isinstance(stock_meta, dict) else "",
        "items": items,
        "universe_count": stock_master_count(),
        "source_count": len([name for name in source_files if (DOCS_DATA / name).exists()]),
    })
    return payload


BUILDERS = {
    "market": ("market-latest.json", build_market_latest),
    "themes": ("themes-latest.json", build_themes_latest),
    "news": ("news-latest.json", build_news_latest),
    "radar": ("radar-latest.json", build_radar_latest),
}


def archive_payload(filename: str, payload: dict, stamp: str) -> None:
    stage = payload.get("stage", "unknown")
    date_dir = ARCHIVE_DIR / stamp[:10]
    archive_path = date_dir / f"{stamp.replace(':', '').replace(' ', 'T')}-{stage}-{filename}"
    write_json(archive_path, payload)


def update_log(stage: str, updated_at: str, data_version: str, updated_files: list[str]) -> dict:
    path = DOCS_DATA / "update-log.json"
    previous = read_json(path, {})
    entries = previous.get("entries") if isinstance(previous, dict) else []
    if not isinstance(entries, list):
        entries = []
    entry = {
        "updated_at": updated_at,
        "stage": stage,
        "stage_label": STAGES[stage]["label"],
        "schedule_time": STAGES[stage]["schedule_time"],
        "timezone": "Asia/Taipei",
        "source_count": len(updated_files),
        "data_version": data_version,
        "updated_files": updated_files,
    }
    warnings = []
    if NEWS_FETCH_STATUS and not NEWS_FETCH_STATUS.get("success", False):
        warnings.append("news_fetch_failed")
        entry["news_fetch_status"] = NEWS_FETCH_STATUS
    payload = {
        "updated_at": updated_at,
        "stage": stage,
        "stage_label": STAGES[stage]["label"],
        "timezone": "Asia/Taipei",
        "source_count": len(updated_files),
        "data_version": data_version,
        "warnings": warnings,
        "news_fetch_status": NEWS_FETCH_STATUS,
        "entries": [entry, *entries][:80],
    }
    write_json(path, payload)
    return payload


def run(stage: str) -> dict:
    global NEWS_FETCH_STATUS
    if stage not in STAGES:
        raise SystemExit(f"unknown stage: {stage}")
    current = now_taipei()
    updated_at = current.strftime("%Y-%m-%d %H:%M:%S Asia/Taipei")
    stamp = current.strftime("%Y-%m-%d %H:%M:%S")
    data_version = current.strftime("%Y%m%d-%H%M") + f"-{stage}"
    updated_files: list[str] = []

    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    if "news" in STAGES[stage]["targets"]:
        NEWS_FETCH_STATUS = refresh_news_events()
        if not NEWS_FETCH_STATUS.get("success", False):
            print(f"[warn] news fetch failed: {NEWS_FETCH_STATUS.get('error') or NEWS_FETCH_STATUS.get('status')}")
    else:
        NEWS_FETCH_STATUS = {}

    for target in STAGES[stage]["targets"]:
        filename, builder = BUILDERS[target]
        payload = builder(stage, updated_at, data_version)
        path = DOCS_DATA / filename
        write_json(path, payload)
        archive_payload(filename, payload, stamp)
        updated_files.append(str(path.relative_to(ROOT)).replace("\\", "/"))

    update_log(stage, updated_at, data_version, updated_files)
    updated_files.append("docs/data/update-log.json")

    return {
        "success": True,
        "updated_at": updated_at,
        "stage": stage,
        "stage_label": STAGES[stage]["label"],
        "data_version": data_version,
        "news_fetch_status": NEWS_FETCH_STATUS,
        "updated_files": updated_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Update GitHub Pages latest radar JSON by stage.")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES), help="update stage")
    args = parser.parse_args()
    print(json.dumps(run(args.stage), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
