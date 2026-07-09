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
    ("full_market_data", "scripts/update_full_market_data.py"),
    ("ai_scorecards", "scripts/build_ai_scorecards.py"),
    ("validate_ai_scoring", "scripts/validate_ai_scoring.py"),
    ("stock_metrics", "scripts/update_stock_metrics.py"),
    ("radar_close_data", "scripts/update_radar.py"),
    ("factor_scores", "scripts/update_factor_scores.py"),
    ("validate_factor_scores", "scripts/validate_factor_scores.py"),
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
}

COMMON_KEYS = {
    "run_id",
    "generated_at",
    "latest_trade_date",
    "data_version",
    "source_pipeline",
}


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
            timeout=1200,
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
            "updated_at",
            "updatedAt",
        ),
    )
    if not value:
        items = get_items(payload)
        if items and isinstance(items[0], dict):
            value = first_existing(
                items[0],
                ("latest_trade_date", "trade_date", "market_date", "date", "dataDate", "data_date", "updatedAt", "updated_at"),
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
    if ROOT_UPDATE_STATUS.exists():
        shutil.copy2(ROOT_UPDATE_STATUS, DOCS_UPDATE_STATUS)


def collect_candidate_dates() -> list[str]:
    dates: list[str] = []
    candidates = STATUS_TARGETS + [
        ROOT_UPDATE_STATUS,
        ROOT_UPDATE_LOG,
        DATA_PROCESSED / "stock_metrics_daily.json",
        DATA_PROCESSED / "ai_scores_daily.json",
        DATA_PROCESSED / "factor-scores.json",
        DATA_PROCESSED / "factor-scores.status.json",
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
    return max(dates) if dates else ""


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


def number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def stock_key(item: dict[str, Any]) -> str:
    return str(item.get("symbol") or item.get("code") or "").strip()


def factor_trade_type(item: dict[str, Any]) -> str:
    total = number_or_none(item.get("total_score")) or 0
    turnover = number_or_none(item.get("turnover_rate_pct")) or 0
    change = abs(number_or_none(item.get("change_pct")) or 0)
    if turnover >= 8 or change >= 5:
        return "短線"
    if total >= 55:
        return "波段"
    return "中長期"


def factor_risk_label(item: dict[str, Any]) -> str:
    risk = str(item.get("risk_level") or "").strip()
    if risk == "高":
        return "過熱"
    if risk == "低":
        return "正常"
    turnover = number_or_none(item.get("turnover_rate_pct"))
    change = number_or_none(item.get("change_pct"))
    volume = number_or_none(item.get("volume"))
    total = number_or_none(item.get("total_score")) or 0
    if (turnover is not None and turnover >= 12) or (change is not None and change >= 7):
        return "過熱"
    if volume is None or volume <= 0:
        return "低流動"
    if total < 30:
        return "冷門"
    return "正常"


def rebuild_factor_scores_from_ai_scores(latest: str, metadata: dict[str, str]) -> dict[str, Any] | None:
    if not latest:
        return None

    factor_scores_path = DATA_PROCESSED / "factor-scores.json"
    factor_status_path = DATA_PROCESSED / "factor-scores.status.json"
    factor_meta_path = DATA_PROCESSED / "factor-scores.meta.json"
    current_scores = read_json(factor_scores_path, [])
    current_status = read_json(factor_status_path, {})
    current_date = payload_date(current_scores)
    status_date = payload_date(current_status)
    if current_date == latest and status_date == latest:
        return None

    ai_payload = read_json(DATA_PROCESSED / "ai_scores_daily.json", {})
    metrics_payload = read_json(DATA_PROCESSED / "stock_metrics_daily.json", {})
    ai_date = payload_date(ai_payload)
    metrics_date = payload_date(metrics_payload)
    ai_items = [item for item in get_items(ai_payload) if isinstance(item, dict)]
    metrics_items = [item for item in get_items(metrics_payload) if isinstance(item, dict)]

    if ai_date != latest or metrics_date != latest or not ai_items:
        return {
            "name": "factor_scores_sync_fallback",
            "script": "scripts/update_all_site_data.py",
            "ok": False,
            "returncode": None,
            "started_at": metadata["generated_at"],
            "finished_at": now_taipei().isoformat(),
            "stdout_tail": "",
            "stderr_tail": "",
            "error": (
                "Cannot rebuild factor scores because source dates are not synchronized: "
                f"ai_scores_daily={ai_date or '--'}, stock_metrics_daily={metrics_date or '--'}, expected={latest}"
            ),
        }

    metrics_by_symbol = {stock_key(item): item for item in metrics_items if stock_key(item)}
    rows: list[dict[str, Any]] = []
    sorted_items = sorted(ai_items, key=lambda item: number_or_none(item.get("total_score")) or -1, reverse=True)[:100]
    revenue_month = first_existing(metrics_payload, ("revenue_month", "financial_period")) or latest[:7]

    for rank, item in enumerate(sorted_items, start=1):
        symbol = stock_key(item)
        metric = metrics_by_symbol.get(symbol, {})
        theme = item.get("theme") or item.get("supply_chain") or item.get("industry") or "未分類"
        row = {
            "rank": rank,
            "code": symbol,
            "symbol": symbol,
            "name": item.get("name") or metric.get("name") or symbol,
            "market": item.get("market") or metric.get("market") or "",
            "industry": item.get("industry") or metric.get("industry") or "",
            "concepts": [theme] if theme else [],
            "close": number_or_none(item.get("trade_price")) if item.get("trade_price") is not None else number_or_none(metric.get("trade_price")),
            "changePercent": number_or_none(item.get("change_pct")) if item.get("change_pct") is not None else number_or_none(metric.get("change_pct")),
            "volume": number_or_none(item.get("volume")) if item.get("volume") is not None else number_or_none(metric.get("volume")),
            "tradeValue": None,
            "listedShares": number_or_none(metric.get("listed_shares")),
            "turnoverRate": number_or_none(item.get("turnover_rate_pct")) if item.get("turnover_rate_pct") is not None else number_or_none(metric.get("turnover_rate_pct")),
            "peRatio": None,
            "pbRatio": None,
            "dividendYield": None,
            "revenueMonth": item.get("financial_period") or metric.get("financial_period") or revenue_month,
            "revenueMillion": number_or_none(item.get("revenue_million")) if item.get("revenue_million") is not None else number_or_none(metric.get("revenue_million")),
            "revenueMomPct": number_or_none(item.get("revenue_mom_pct")) if item.get("revenue_mom_pct") is not None else number_or_none(metric.get("revenue_mom_pct")),
            "revenueYoyPct": number_or_none(item.get("revenue_yoy_pct")) if item.get("revenue_yoy_pct") is not None else number_or_none(metric.get("revenue_yoy_pct")),
            "eps": number_or_none(item.get("eps")) if item.get("eps") is not None else number_or_none(metric.get("eps")),
            "grossMarginPct": number_or_none(item.get("gross_margin_pct")) if item.get("gross_margin_pct") is not None else number_or_none(metric.get("gross_margin_pct")),
            "fundamentalScore": number_or_none(item.get("fundamental_score")),
            "technicalScore": number_or_none(item.get("technical_score")),
            "chipScore": number_or_none(item.get("chip_score")),
            "turnoverScore": number_or_none(item.get("turnover_score")),
            "totalScore": number_or_none(item.get("total_score")),
            "tradeType": factor_trade_type(item),
            "riskLabel": factor_risk_label(item),
            "updatedAt": metadata["generated_at"],
            "dataDate": latest,
            "scoreSource": "ai_scores_daily + stock_metrics_daily",
        }
        rows.append(row)

    status_payload = {
        **metadata,
        "ok": True,
        "status": "ok",
        "updated_at": metadata["generated_at"],
        "attempted_at": metadata["generated_at"],
        "target_date": latest,
        "latest_trade_date": latest,
        "items_count": len(rows),
        "rows_written": len(rows),
        "previous_data_preserved": False,
        "failed_reasons": [],
        "warnings": ["多因子分數由全市場 AI 分數與行情資料同步重建，未使用新聞面評分。"],
        "quality": {
            "ai_score_rows": len(ai_items),
            "metrics_rows": len(metrics_items),
            "factor_rows": len(rows),
        },
        "source_status": [
            {"source": "ai_scores_daily.json", "status": "ok", "latest_trade_date": ai_date, "rows": len(ai_items)},
            {"source": "stock_metrics_daily.json", "status": "ok", "latest_trade_date": metrics_date, "rows": len(metrics_items)},
        ],
    }
    meta_payload = {
        **metadata,
        "latest_trade_date": latest,
        "updated_at": metadata["generated_at"],
        "items_count": len(rows),
        "score_version": "unified-ai-metrics-v1",
        "weights": {
            "fundamental": "from ai_scores_daily",
            "technical": "from ai_scores_daily",
            "chip": "from ai_scores_daily",
            "turnover": "from ai_scores_daily",
            "news": "not used by factor-score page",
        },
    }
    write_json(factor_scores_path, rows)
    write_json(factor_status_path, status_payload)
    write_json(factor_meta_path, meta_payload)
    return {
        "name": "factor_scores_sync_fallback",
        "script": "scripts/update_all_site_data.py",
        "ok": True,
        "returncode": 0,
        "started_at": metadata["generated_at"],
        "finished_at": now_taipei().isoformat(),
        "stdout_tail": f"Rebuilt {len(rows)} factor score rows from synchronized AI scores and metrics.",
        "stderr_tail": "",
        "error": "",
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


def annotate_outputs(metadata: dict[str, str]) -> None:
    for path in STATUS_TARGETS + [ROOT_UPDATE_STATUS, ROOT_UPDATE_LOG]:
        annotate_json_file(path, metadata)


def file_status(path: Path, expected_latest: str) -> dict[str, Any]:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    payload = read_json(path, {})
    exists = path.exists()
    items = get_items(payload)
    date = payload_date(payload)
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
    failed_reasons: list[str] = [
        f"{step['name']}: {step['error']}"
        for step in step_results
        if not step["ok"] and step.get("error")
    ]
    for item in files:
        if item["status"] in {"failed", "missing", "stale"}:
            failed_reasons.extend(f"{item['file']}: {reason}" for reason in item["failed_reasons"])

    warnings = freshness_warnings(latest, datetime.fromisoformat(metadata["generated_at"]))
    status = "ok"
    if failed_reasons:
        status = "failed"
    elif stale_files or warnings:
        status = "stale" if stale_files else "warning"

    payload = {
        **metadata,
        "status": status,
        "ok": status == "ok",
        "each_file_status": files,
        "files": files,
        "stale_files": sorted(set(stale_files)),
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


def main() -> int:
    step_results = [run_step(name, script) for name, script in STEPS]

    now = now_taipei()
    latest = latest_trade_date()
    metadata = make_metadata(now, latest)

    fallback_result = rebuild_factor_scores_from_ai_scores(latest, metadata)
    if fallback_result:
        step_results.append(fallback_result)

    sync_processed_to_docs()
    copy_status_sidecars()

    latest = latest_trade_date()
    if latest != metadata["latest_trade_date"]:
        metadata = make_metadata(now, latest)
    annotate_outputs(metadata)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
