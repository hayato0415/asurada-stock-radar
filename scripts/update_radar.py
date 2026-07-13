from __future__ import annotations

import json
import math
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from official_daily_quotes import fetch_daily_quotes
except ModuleNotFoundError:  # Supports importing as scripts.update_radar in tests.
    from scripts.official_daily_quotes import fetch_daily_quotes


TAIPEI = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "data"
RADAR_PATH = DATA_DIR / "radar.json"
STATUS_PATH = DATA_DIR / "update_status.json"
STOCK_MASTER_PATH = ROOT / "data" / "processed" / "stocks_master.json"
MIN_QUOTE_COVERAGE_RATIO = 0.80

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


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def market_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"上市", "twse", "listed"} or "上市" in text:
        return "twse"
    if text in {"上櫃", "tpex", "otc"} or "上櫃" in text:
        return "tpex"
    return ""


def unique_market_counts(items: Any) -> dict[str, int]:
    symbols: dict[str, set[str]] = {"twse": set(), "tpex": set()}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        market = market_key(item.get("market"))
        symbol = normalize_code(item.get("symbol") or item.get("code"))
        if market in symbols and symbol:
            symbols[market].add(symbol)
    return {market: len(values) for market, values in symbols.items()}


def quote_coverage_requirements() -> dict[str, int]:
    master = read_json(STOCK_MASTER_PATH, {})
    master_counts = unique_market_counts(master.get("items", []) if isinstance(master, dict) else [])
    previous = read_json(RADAR_PATH, {})
    previous_counts = unique_market_counts(previous.get("items", []) if isinstance(previous, dict) else [])
    return {
        market: max(1, math.ceil(max(master_counts[market], previous_counts[market]) * MIN_QUOTE_COVERAGE_RATIO))
        for market in ("twse", "tpex")
    }


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
            pick(row, ["TradingShares", "TradingVolume", "TradeVolume", "成交股數", "成交股數(股)", "成交量", "volume"])
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


def failure_payload(now: datetime, message: str, errors: list[str], previous_trade_date: str) -> dict[str, Any]:
    updated_at = iso_datetime(now)
    return {
        "status": "failed",
        "message": message,
        "trade_date": previous_trade_date,
        "target_date": now.date().isoformat(),
        "updated_at": updated_at,
        "timezone": "Asia/Taipei",
        "source": [],
        "items_count": 0,
        "errors": errors,
        "previous_data_preserved": True,
    }


def main() -> int:
    now = now_taipei()
    updated_at = iso_datetime(now)
    requested_date = now.date().isoformat()
    errors: list[str] = []
    sources: list[str] = []
    source_dates: dict[str, str] = {}
    items: list[dict[str, Any]] = []

    for market in ("twse", "tpex"):
        try:
            rows, source_date, source_url = fetch_daily_quotes(market, requested_date)
            normalized = (
                normalize_twse(rows, updated_at, source_date)
                if market == "twse"
                else normalize_tpex(rows, updated_at, source_date)
            )
            if not normalized:
                raise ValueError("official response returned no normalized stock rows")
            items.extend(normalized)
            sources.append(source_url)
            source_dates[market] = source_date
        except Exception as exc:  # noqa: BLE001 - preserve old radar and report exact source error.
            errors.append(f"{market.upper()} daily close fetch failed: {exc}")

    unique_dates = sorted(set(source_dates.values()))
    if len(unique_dates) != 1:
        errors.append(f"Official daily quote dates do not match: {source_dates}")
    trade_date = unique_dates[0] if len(unique_dates) == 1 else ""
    matched_quote_counts = unique_market_counts(items)
    required_quote_counts = quote_coverage_requirements()
    for market in ("twse", "tpex"):
        actual = matched_quote_counts[market]
        required = required_quote_counts[market]
        if actual < required:
            errors.append(
                f"{market.upper()} radar quote coverage {actual} is below safety threshold {required} "
                f"({MIN_QUOTE_COVERAGE_RATIO:.0%} of stock master/prior radar)"
            )

    if errors or not items or not trade_date:
        message = "TWSE/TPEx close refresh failed; previous radar.json was preserved."
        previous = read_json(RADAR_PATH, {})
        previous_trade_date = str(previous.get("trade_date") or previous.get("latest_trade_date") or "")
        status = failure_payload(now, message, errors or [message], previous_trade_date)
        write_json(STATUS_PATH, status)
        print(f"failed: {message}")
        for error in status["errors"]:
            print(f"- {error}")
        return 1

    message = f"Fetched {len(items)} TWSE/TPEx close rows for {trade_date}."
    status = {
        "status": "success",
        "message": message,
        "trade_date": trade_date,
        "updated_at": updated_at,
        "timezone": "Asia/Taipei",
        "source": sources,
        "source_dates": source_dates,
        "items_count": len(items),
        "errors": [],
        "previous_data_preserved": False,
        "quality": {
            "matched_by_market": matched_quote_counts,
            "required_by_market": required_quote_counts,
            "minimum_ratio": MIN_QUOTE_COVERAGE_RATIO,
        },
    }
    radar = {**status, "items": sorted(items, key=lambda item: item["code"])}

    write_json(RADAR_PATH, radar)
    write_json(STATUS_PATH, status)
    print(f"{status['status']}: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
