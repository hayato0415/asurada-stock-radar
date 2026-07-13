#!/usr/bin/env python
"""Build news_events.json from official TWSE and TPEx disclosures.

The source datasets contain company material-information disclosures, not
editorial news.  This updater therefore copies only official source fields and
uses explicit "unscored" / "undetermined" labels instead of inventing market
impact, themes, or AI judgements.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # GitHub Actions installs requests; urllib remains a local fallback.
    requests = None


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "processed" / "news_events.json"

TAIPEI = timezone(timedelta(hours=8))
USER_AGENT = "ASURADA-Stock-Radar/1.0 (+https://github.com/hayato0415/asurada-stock-radar)"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    market: str
    name: str
    url: str
    snapshot_keys: tuple[str, ...]
    symbol_keys: tuple[str, ...]
    company_keys: tuple[str, ...]


SOURCES = (
    SourceSpec(
        key="twse",
        market="上市",
        name="臺灣證券交易所重大訊息",
        url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        snapshot_keys=("出表日期",),
        symbol_keys=("公司代號",),
        company_keys=("公司名稱",),
    ),
    SourceSpec(
        key="tpex",
        market="上櫃",
        name="櫃檯買賣中心重大訊息",
        url="https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
        snapshot_keys=("Date", "出表日期"),
        symbol_keys=("SecuritiesCompanyCode", "公司代號"),
        company_keys=("CompanyName", "公司名稱"),
    ),
)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(microsecond=0)


def clean_text(value: Any) -> str:
    """Collapse source formatting without changing its words or meaning."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def row_value(row: dict[str, Any], *keys: str) -> Any:
    normalized = {str(key).strip(): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key.strip())
        if value not in (None, ""):
            return value
    return None


def parse_source_date(value: Any, field: str) -> date:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 7:
        year = int(digits[:3]) + 1911
        month = int(digits[3:5])
        day = int(digits[5:7])
    elif len(digits) == 8:
        year = int(digits[:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
    else:
        raise ValueError(f"{field} is not a ROC/Gregorian calendar date: {value!r}")
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"{field} is invalid: {value!r}") from exc


def parse_source_time(value: Any, field: str) -> time:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits or len(digits) > 6:
        raise ValueError(f"{field} is not HHMMSS: {value!r}")
    digits = digits.zfill(6)
    try:
        return time(int(digits[:2]), int(digits[2:4]), int(digits[4:6]))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid: {value!r}") from exc


def _decode_response(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8-sig"))


def _fetch_with_urllib(url: str, *, verify_tls: bool = True) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    context = None if verify_tls else ssl._create_unverified_context()  # noqa: SLF001 - exact official host fallback.
    with urllib.request.urlopen(request, timeout=45, context=context) as response:  # noqa: S310 - fixed official URLs.
        return _decode_response(response.read())


def fetch_json(url: str) -> list[dict[str, Any]]:
    """Fetch one fixed official endpoint and reject empty or malformed replies."""
    if requests is not None:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=45,
            )
        except requests.exceptions.SSLError:
            if not url.startswith("https://www.tpex.org.tw/"):
                raise
            # Some Windows CA stacks reject the TPEx certificate extension even
            # though the same fixed official host validates on GitHub runners.
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=45,
                verify=False,
            )
        response.raise_for_status()
        response.encoding = "utf-8"
        payload = response.json()
    else:
        try:
            payload = _fetch_with_urllib(url)
        except (ssl.SSLError, urllib.error.URLError):
            if not url.startswith("https://www.tpex.org.tw/"):
                raise
            payload = _fetch_with_urllib(url, verify_tls=False)

    if not isinstance(payload, list) or not payload:
        raise ValueError(f"official endpoint returned no usable rows: {url}")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"official endpoint returned non-object rows: {url}")
    return payload


def event_id(spec: SourceSpec, published_at: str, symbol: str, title: str) -> str:
    digest_source = json.dumps(
        [spec.key, published_at, symbol, title],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    return f"mops-{spec.key}-{symbol}-{digest}"


def normalize_row(spec: SourceSpec, row: dict[str, Any], row_number: int) -> dict[str, Any]:
    prefix = f"{spec.key} row {row_number}"
    snapshot = parse_source_date(row_value(row, *spec.snapshot_keys), f"{prefix} snapshot date")
    published_date = parse_source_date(row_value(row, "發言日期"), f"{prefix} published date")
    published_time = parse_source_time(row_value(row, "發言時間"), f"{prefix} published time")
    if published_date > snapshot:
        raise ValueError(f"{prefix} published date is after source snapshot date")

    symbol = clean_text(row_value(row, *spec.symbol_keys)).upper()
    if not re.fullmatch(r"\d{4,6}", symbol):
        raise ValueError(f"{prefix} company code is invalid: {symbol!r}")

    company_name = clean_text(row_value(row, *spec.company_keys))
    title = clean_text(row_value(row, "主旨"))
    details = clean_text(row_value(row, "說明"))
    if not company_name or not title:
        raise ValueError(f"{prefix} is missing company name or subject")

    disclosure_rule = clean_text(row_value(row, "符合條款")) or None
    raw_event_date = row_value(row, "事實發生日")
    official_event_date = (
        parse_source_date(raw_event_date, f"{prefix} event date").isoformat()
        if raw_event_date not in (None, "")
        else None
    )
    published = datetime.combine(published_date, published_time, tzinfo=TAIPEI).isoformat()

    return {
        "id": event_id(spec, published, symbol, title),
        "published_at": published,
        "title": title,
        "summary": details or title,
        "source_name": spec.name,
        "source_grade": "官方",
        "source_url": spec.url,
        "source_market": spec.key,
        "source_snapshot_date": snapshot.isoformat(),
        "official_event_date": official_event_date,
        "disclosure_rule": disclosure_rule,
        "region": "台股",
        "market": spec.market,
        "theme": "公司重大訊息",
        "impact": "未判定",
        "news_score": None,
        "score_status": "未評分",
        "stocks": [{"code": symbol, "name": company_name}],
        "ai_judgement": "未判定（未執行 AI 多空判讀）",
        "operation_meaning": "僅同步官方揭露，不提供操作判斷。",
    }


def normalize_source(spec: SourceSpec, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not rows:
        raise ValueError(f"{spec.key} returned no rows")

    items = [normalize_row(spec, row, index) for index, row in enumerate(rows, start=1)]
    snapshot_dates = {item["source_snapshot_date"] for item in items}
    if len(snapshot_dates) != 1:
        raise ValueError(f"{spec.key} contains mixed source snapshot dates: {sorted(snapshot_dates)}")

    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{spec.key} contains duplicate normalized disclosure identifiers")
    return items, snapshot_dates.pop()


def build_payload(source_rows: dict[str, list[dict[str, Any]]], generated_at: datetime | None = None) -> dict[str, Any]:
    generated_at = (generated_at or now_taipei()).astimezone(TAIPEI).replace(microsecond=0)
    items: list[dict[str, Any]] = []
    snapshot_dates: dict[str, str] = {}
    source_status: list[dict[str, Any]] = []

    for spec in SOURCES:
        rows = source_rows.get(spec.key)
        if not isinstance(rows, list):
            raise ValueError(f"missing source rows for {spec.key}")
        normalized, snapshot_date = normalize_source(spec, rows)
        items.extend(normalized)
        snapshot_dates[spec.key] = snapshot_date
        source_status.append(
            {
                "source": spec.key,
                "source_name": spec.name,
                "source_url": spec.url,
                "status": "ok",
                "source_snapshot_date": snapshot_date,
                "rows": len(normalized),
            }
        )

    if not items:
        raise ValueError("official sources produced no normalized disclosures")
    item_ids = [item["id"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("official sources produced duplicate normalized disclosure identifiers")

    unique_snapshot_dates = sorted(set(snapshot_dates.values()))
    if len(unique_snapshot_dates) != 1:
        raise ValueError(f"official sources have different snapshot dates: {snapshot_dates}")

    items.sort(key=lambda item: (item["published_at"], item["source_market"], item["id"]), reverse=True)
    source_snapshot_date = unique_snapshot_dates[0]
    content_latest_at = max(item["published_at"] for item in items)
    generated_iso = generated_at.isoformat()
    run_id = os.getenv("GITHUB_RUN_ID") or generated_at.strftime("%Y%m%d%H%M%S")

    return {
        "status": "ok",
        "ok": True,
        "updated_at": generated_iso,
        "generated_at": generated_iso,
        "run_id": str(run_id),
        "data_version": f"{source_snapshot_date.replace('-', '')}-{generated_at:%H%M}",
        "source_pipeline": "update_news_events",
        "source_snapshot_date": source_snapshot_date,
        "source_snapshot_dates": snapshot_dates,
        "content_latest_at": content_latest_at,
        "source_status": source_status,
        "quality": {
            "source_count": len(SOURCES),
            "item_count": len(items),
            "scored_item_count": 0,
            "impact_determined_count": 0,
            "note": "全部事件為官方重大訊息；未自行評分或判定多空。",
        },
        "items": items,
    }


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def same_source_content(existing: Any, payload: dict[str, Any]) -> bool:
    if not isinstance(existing, dict):
        return False
    return all(
        existing.get(key) == payload.get(key)
        for key in ("source_snapshot_date", "source_snapshot_dates", "content_latest_at", "items")
    )


def write_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    """Atomically write new source content; return False for an unchanged snapshot."""
    if same_source_content(read_json(path), payload):
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def main() -> int:
    source_rows: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for spec in SOURCES:
        try:
            source_rows[spec.key] = fetch_json(spec.url)
        except Exception as exc:  # Preserve the previous file after any source failure.
            errors.append(f"{spec.key}: {type(exc).__name__}: {exc}")

    if errors:
        print("News events update failed; previous data was preserved.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    try:
        payload = build_payload(source_rows)
    except Exception as exc:
        print(
            f"News events normalization failed; previous data was preserved: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    changed = write_if_changed(OUTPUT, payload)
    action = "updated" if changed else "unchanged"
    print(
        f"News events {action}: {len(payload['items'])} official disclosures; "
        f"source_snapshot_date={payload['source_snapshot_date']}; "
        f"content_latest_at={payload['content_latest_at']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
