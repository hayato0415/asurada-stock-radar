#!/usr/bin/env python3
"""Fetch Taiwan listed-market snapshot from TWSE public JSON.

The script only overwrites `daily_market_snapshot.json` when it can parse
usable market data. If TWSE has no current data yet, it preserves the last
successful snapshot and marks it stale without faking `updated_at`.
"""

from __future__ import annotations

import json
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
DATA = ROOT / "data"
try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(microsecond=0)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def to_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    text = text.replace("--", "").replace("X", "")
    text = re.sub(r"[^\d.+-]", "", text)
    if not text or text in {"+", "-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_twse_mi_index(date_text: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode(
        {
            "date": date_text,
            "type": "ALLBUT0999",
            "response": "json",
        }
    )
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 asurada-stock-radar/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    stat = str(payload.get("stat") or "")
    if "OK" not in stat and "很抱歉" in stat:
        return None
    return payload


def find_table(payload: dict[str, Any], wanted_fields: list[str]) -> tuple[list[str], list[list[Any]]] | None:
    for key, value in payload.items():
        if not key.startswith("fields") or not isinstance(value, list):
            continue
        suffix = key.replace("fields", "")
        data = payload.get(f"data{suffix}")
        if not isinstance(data, list):
            continue
        fields = [str(field) for field in value]
        if all(any(wanted in field for field in fields) for wanted in wanted_fields):
            return fields, data
    return None


def parse_index_row(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, rows in payload.items():
        if not key.startswith("data") or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list):
                continue
            text = " ".join(str(cell) for cell in row)
            if "發行量加權股價指數" not in text and "加權指數" not in text:
                continue
            numbers = [to_number(cell) for cell in row]
            numbers = [number for number in numbers if number is not None]
            if numbers:
                result["taiex"] = numbers[0]
            if len(numbers) >= 2:
                result["change"] = numbers[-2] if len(numbers) >= 3 else numbers[-1]
            if len(numbers) >= 3:
                result["change_pct"] = numbers[-1]
            return result
    return result


def parse_stock_counts(payload: dict[str, Any]) -> dict[str, Any]:
    table = find_table(payload, ["證券代號", "收盤價", "漲跌"])
    if not table:
        return {}
    fields, rows = table
    close_idx = next((i for i, field in enumerate(fields) if "收盤價" in field), None)
    change_idx = next((i for i, field in enumerate(fields) if "漲跌" in field and "價差" in field), None)
    sign_idx = next((i for i, field in enumerate(fields) if "漲跌" in field and "(+/-)" in field), None)
    volume_idx = next((i for i, field in enumerate(fields) if "成交股數" in field), None)

    up_count = down_count = limit_up_count = limit_down_count = 0
    total_volume_shares = 0.0

    for row in rows:
        if not isinstance(row, list):
            continue
        close = to_number(row[close_idx]) if close_idx is not None and close_idx < len(row) else None
        change = to_number(row[change_idx]) if change_idx is not None and change_idx < len(row) else None
        sign = str(row[sign_idx]).strip() if sign_idx is not None and sign_idx < len(row) else ""
        volume = to_number(row[volume_idx]) if volume_idx is not None and volume_idx < len(row) else None
        if volume:
            total_volume_shares += volume
        if change is None:
            continue
        is_up = change > 0 or sign == "+"
        is_down = change < 0 or sign == "-"
        if is_up:
            up_count += 1
        if is_down:
            down_count += 1
        if close and change:
            previous = close - change if is_up else close + abs(change)
            if previous:
                pct = abs(change) / previous * 100
                if is_up and pct >= 9.5:
                    limit_up_count += 1
                if is_down and pct >= 9.5:
                    limit_down_count += 1

    return {
        "up_count": up_count or None,
        "down_count": down_count or None,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "volume_shares": total_volume_shares or None,
    }


def build_snapshot(date_text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    index_data = parse_index_row(payload)
    counts = parse_stock_counts(payload)
    if not index_data and not counts:
        return None

    date_display = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    updated_at = now_taipei().strftime("%Y-%m-%d %H:%M:%S")
    snapshot = {
        "date": date_display,
        "updated_at": updated_at,
        "session": "上市收盤資料",
        "source": "TWSE",
        "source_url": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
        "source_count": 1,
        "taiex": index_data.get("taiex"),
        "change": index_data.get("change"),
        "change_pct": index_data.get("change_pct"),
        "up_count": counts.get("up_count"),
        "down_count": counts.get("down_count"),
        "limit_up_count": counts.get("limit_up_count"),
        "limit_down_count": counts.get("limit_down_count"),
        "volume_shares": counts.get("volume_shares"),
        "data_quality_warning": "",
        "stale": False,
        "stale_reason": "",
    }
    if counts.get("volume_shares"):
        snapshot["volume_billion"] = round(counts["volume_shares"] / 100_000_000, 2)
    return snapshot


def preserve_previous(reason: str) -> dict[str, Any]:
    previous = read_json(DOCS_DATA / "daily_market_snapshot.json")
    if not previous:
        previous = {
            "date": "",
            "updated_at": "",
            "session": "",
            "source": "TWSE",
            "source_count": 0,
        }
    previous["stale"] = True
    previous["stale_reason"] = reason
    previous["data_quality_warning"] = reason
    previous["last_attempt_at"] = now_taipei().strftime("%Y-%m-%d %H:%M:%S")
    return previous


def main() -> None:
    today = now_taipei().date()
    errors: list[str] = []
    for offset in range(0, 10):
        target = today - timedelta(days=offset)
        if target.weekday() >= 5:
            continue
        date_text = target.strftime("%Y%m%d")
        try:
            payload = fetch_twse_mi_index(date_text)
            if not payload:
                errors.append(f"{date_text}: TWSE 無資料")
                continue
            snapshot = build_snapshot(date_text, payload)
            if not snapshot:
                errors.append(f"{date_text}: 無法解析 TWSE 欄位")
                continue
            write_json_atomic(DOCS_DATA / "daily_market_snapshot.json", snapshot)
            write_json_atomic(DATA / "daily_market_snapshot.json", snapshot)
            print(f"market snapshot updated: {snapshot['date']}")
            return
        except Exception as exc:
            errors.append(f"{date_text}: {exc}")

    reason = "TWSE 市場快照未取得新資料，保留上一版；" + "；".join(errors[-3:])
    snapshot = preserve_previous(reason)
    write_json_atomic(DOCS_DATA / "daily_market_snapshot.json", snapshot)
    write_json_atomic(DATA / "daily_market_snapshot.json", snapshot)
    print(reason)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
