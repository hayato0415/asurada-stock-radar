from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TAIPEI = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "data"
RADAR_PATH = DATA_DIR / "radar.json"
STATUS_PATH = DATA_DIR / "update_status.json"

TWSE_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
SSL_CONTEXT = ssl._create_unverified_context()


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def iso_datetime(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ASURADA-Stock-Radar/1.0 (+https://github.com/hayato0415/asurada-stock-radar)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
        raw = response.read().decode("utf-8-sig", errors="replace")
    return json.loads(raw)


def pick(row: dict[str, Any], candidates: list[str]) -> Any:
    if not isinstance(row, dict):
        return None
    for key in candidates:
        if key in row:
            return row[key]

    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in candidates:
        value = normalized.get(str(key).strip().lower())
        if value is not None:
            return value
    return None


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{4}", text) else ""


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "null", "None"}:
        return None
    text = text.replace(",", "").replace("%", "")
    text = text.replace("＋", "+").replace("－", "-")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    number = parse_number(value)
    if number is None:
        return None
    return int(round(number))


def parse_change_percent(row: dict[str, Any], close: float | None) -> float | None:
    direct = parse_number(
        pick(
            row,
            [
                "ChangePercent",
                "PercentChange",
                "ChangePercent%",
                "漲跌幅",
                "漲跌幅(%)",
                "漲跌百分比",
            ],
        )
    )
    if direct is not None:
        return direct

    change = parse_number(pick(row, ["Change", "漲跌價差", "漲跌", "漲跌(+/-)"]))
    previous = parse_number(pick(row, ["PreviousClose", "昨收", "前日收盤價"]))
    if change is not None and previous not in (None, 0):
        return (change / previous) * 100
    if change is not None and close is not None and (close - change) != 0:
        return (change / (close - change)) * 100
    return None


def normalize_twse(rows: list[dict[str, Any]], updated_at: str, trade_date: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        code = normalize_code(pick(row, ["Code", "證券代號", "股票代號", "code"]))
        name = str(pick(row, ["Name", "證券名稱", "股票名稱", "name"]) or "").strip()
        if not code or not name:
            continue
        close = parse_number(pick(row, ["ClosingPrice", "Close", "收盤價", "收盤", "close"]))
        volume = parse_int(pick(row, ["TradeVolume", "TradingVolume", "成交股數", "成交股數(股)", "成交量", "volume"]))
        change_percent = parse_change_percent(row, close)
        items.append(
            {
                "code": code,
                "symbol": code,
                "name": name,
                "market": "上市",
                "close": close,
                "trade_price": close,
                "volume": volume,
                "change_percent": change_percent,
                "change_pct": change_percent,
                "trade_date": trade_date,
                "updated_at": updated_at,
                "source": "TWSE STOCK_DAY_ALL",
            }
        )
    return items


def normalize_tpex(rows: list[dict[str, Any]], updated_at: str, trade_date: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        code = normalize_code(
            pick(row, ["SecuritiesCompanyCode", "Code", "代號", "證券代號", "股票代號", "code"])
        )
        name = str(
            pick(row, ["CompanyName", "Name", "名稱", "證券名稱", "股票名稱", "name"]) or ""
        ).strip()
        if not code or not name:
            continue
        close = parse_number(pick(row, ["Close", "ClosingPrice", "收盤價", "收盤", "close"]))
        volume = parse_int(
            pick(row, ["TradingVolume", "TradeVolume", "成交股數", "成交股數(股)", "成交量", "volume"])
        )
        change_percent = parse_change_percent(row, close)
        items.append(
            {
                "code": code,
                "symbol": code,
                "name": name,
                "market": "上櫃",
                "close": close,
                "trade_price": close,
                "volume": volume,
                "change_percent": change_percent,
                "change_pct": change_percent,
                "trade_date": trade_date,
                "updated_at": updated_at,
                "source": "TPEx daily close quotes",
            }
        )
    return items


def failure_payload(now: datetime, message: str, errors: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    updated_at = iso_datetime(now)
    base = {
        "status": "failed",
        "message": message,
        "trade_date": now.date().isoformat(),
        "updated_at": updated_at,
        "timezone": "Asia/Taipei",
        "source": [],
        "items_count": 0,
        "errors": errors,
    }
    return {**base, "items": []}, base


def main() -> int:
    now = now_taipei()
    updated_at = iso_datetime(now)
    trade_date = now.date().isoformat()
    errors: list[str] = []
    sources: list[str] = []
    items: list[dict[str, Any]] = []

    if now.weekday() >= 5:
        message = f"{trade_date} is not a Taiwan trading day. No close data was fetched."
        radar, status = failure_payload(now, message, [message])
        write_json(RADAR_PATH, radar)
        write_json(STATUS_PATH, status)
        print(message)
        return 0

    try:
        twse_payload = fetch_json(TWSE_STOCK_DAY_ALL)
        if isinstance(twse_payload, list):
            twse_items = normalize_twse(twse_payload, updated_at, trade_date)
            items.extend(twse_items)
            if twse_items:
                sources.append("TWSE STOCK_DAY_ALL")
            else:
                errors.append("TWSE STOCK_DAY_ALL returned no normalized listed-stock rows.")
        else:
            errors.append("TWSE STOCK_DAY_ALL did not return a JSON array.")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"TWSE STOCK_DAY_ALL fetch failed: {exc}")

    try:
        tpex_payload = fetch_json(TPEX_DAILY_QUOTES)
        if isinstance(tpex_payload, list):
            tpex_items = normalize_tpex(tpex_payload, updated_at, trade_date)
            items.extend(tpex_items)
            if tpex_items:
                sources.append("TPEx daily close quotes")
            else:
                errors.append("TPEx daily close quotes returned no normalized OTC-stock rows.")
        else:
            errors.append("TPEx daily close quotes did not return a JSON array.")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"TPEx daily close quotes fetch failed: {exc}")

    if not items:
        message = "No TWSE/TPEx close data was fetched. This may be a non-trading day or official data may not be updated yet."
        radar, status = failure_payload(now, message, errors or [message])
    else:
        message = f"Fetched {len(items)} TWSE/TPEx close rows."
        status = {
            "status": "success",
            "message": message,
            "trade_date": trade_date,
            "updated_at": updated_at,
            "timezone": "Asia/Taipei",
            "source": sources,
            "items_count": len(items),
            "errors": errors,
        }
        radar = {**status, "items": sorted(items, key=lambda item: item["code"])}

    write_json(RADAR_PATH, radar)
    write_json(STATUS_PATH, status)
    print(f"{status['status']}: {message}")
    if errors:
        print("errors:")
        for error in errors:
            print(f"- {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
