"""Fetch authoritative TWSE/TPEx daily close rows with a real trade date."""

from __future__ import annotations

import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - urllib keeps Actions usable.
    requests = None


TAIPEI = timezone(timedelta(hours=8))
USER_AGENT = "ASURADA-Stock-Radar/2.0 (+https://github.com/hayato0415/asurada-stock-radar)"
TWSE_OPENAPI = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_HOLIDAY_SCHEDULE = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
TAIEX_MONTHLY_HISTORY = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
AFTER_CLOSE_CUTOFF = time(15, 20)
HOLIDAY_MARKERS = ("放假", "休市", "市場無交易")
OPEN_MARKERS = ("開始交易", "最後交易")


def parse_trade_date(value: Any) -> str:
    """Normalize ISO, Gregorian compact, or ROC dates to YYYY-MM-DD."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        digits = re.sub(r"\D", "", text)
        if len(digits) != 7:
            return ""
        year, month, day = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


def _fetch_json(url: str) -> Any:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"}
    if requests is not None:
        try:
            response = requests.get(url, headers=headers, timeout=45)
        except requests.exceptions.SSLError:
            response = requests.get(url, headers=headers, timeout=45, verify=False)
        response.raise_for_status()
        return response.json()
    request = urllib.request.Request(url, headers=headers)
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=45, context=context) as response:
        return json.loads(response.read().decode("utf-8-sig", errors="replace"))


def _clean_text(value: Any) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def _find_table(payload: dict[str, Any], required_fields: set[str]) -> tuple[list[str], list[list[Any]]]:
    for table in payload.get("tables", []):
        fields = table.get("fields") or []
        if required_fields.issubset(set(fields)) and isinstance(table.get("data"), list):
            return fields, table["data"]
    raise ValueError(f"official response is missing fields: {sorted(required_fields)}")


def _twse_date_specific(target_date: str) -> tuple[list[dict[str, Any]], str, str]:
    compact = target_date.replace("-", "")
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?"
        + urllib.parse.urlencode({"date": compact, "type": "ALLBUT0999", "response": "json"})
    )
    payload = _fetch_json(url)
    if not isinstance(payload, dict) or str(payload.get("stat", "")).upper() != "OK":
        raise ValueError(f"TWSE date-specific response not ready for {target_date}")
    source_date = parse_trade_date(payload.get("date"))
    if source_date != target_date:
        raise ValueError(f"TWSE returned {source_date or '--'} for requested {target_date}")
    fields, data = _find_table(payload, {"證券代號", "證券名稱", "收盤價"})
    rows: list[dict[str, Any]] = []
    for values in data:
        raw = dict(zip(fields, values))
        sign = _clean_text(raw.get("漲跌(+/-)"))
        change = _clean_text(raw.get("漲跌價差"))
        if change and sign.startswith("-") and not change.startswith("-"):
            change = f"-{change}"
        rows.append(
            {
                "Date": source_date,
                "Code": _clean_text(raw.get("證券代號")),
                "Name": _clean_text(raw.get("證券名稱")),
                "TradeVolume": _clean_text(raw.get("成交股數")),
                "TradeValue": _clean_text(raw.get("成交金額")),
                "OpeningPrice": _clean_text(raw.get("開盤價")),
                "HighestPrice": _clean_text(raw.get("最高價")),
                "LowestPrice": _clean_text(raw.get("最低價")),
                "ClosingPrice": _clean_text(raw.get("收盤價")),
                "Change": change,
                "Transaction": _clean_text(raw.get("成交筆數")),
            }
        )
    if not rows:
        raise ValueError(f"TWSE returned zero close rows for {target_date}")
    return rows, source_date, url


def _tpex_date_specific(target_date: str) -> tuple[list[dict[str, Any]], str, str]:
    url = (
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?"
        + urllib.parse.urlencode({"date": target_date.replace("-", "/"), "id": "", "response": "json"})
    )
    payload = _fetch_json(url)
    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() != "ok":
        raise ValueError(f"TPEx date-specific response not ready for {target_date}")
    source_date = parse_trade_date(payload.get("date"))
    if source_date != target_date:
        raise ValueError(f"TPEx returned {source_date or '--'} for requested {target_date}")
    fields, data = _find_table(payload, {"代號", "名稱", "收盤"})
    rows: list[dict[str, Any]] = []
    for values in data:
        raw = dict(zip(fields, values))
        rows.append(
            {
                "Date": source_date,
                "SecuritiesCompanyCode": _clean_text(raw.get("代號")),
                "CompanyName": _clean_text(raw.get("名稱")),
                "Close": _clean_text(raw.get("收盤")),
                "Change": _clean_text(raw.get("漲跌")),
                "Open": _clean_text(raw.get("開盤")),
                "High": _clean_text(raw.get("最高")),
                "Low": _clean_text(raw.get("最低")),
                "Average": _clean_text(raw.get("均價")),
                "TradingShares": _clean_text(raw.get("成交股數")),
                "TradingVolume": _clean_text(raw.get("成交股數")),
                "TransactionAmount": _clean_text(raw.get("成交金額(元)")),
                "TradeValue": _clean_text(raw.get("成交金額(元)")),
                "TransactionNumber": _clean_text(raw.get("成交筆數")),
                "Capitals": _clean_text(raw.get("發行股數")),
            }
        )
    if not rows:
        raise ValueError(f"TPEx returned zero close rows for {target_date}")
    return rows, source_date, url


def _openapi_fallback(market: str) -> tuple[list[dict[str, Any]], str, str]:
    url = TWSE_OPENAPI if market == "twse" else TPEX_OPENAPI
    payload = _fetch_json(url)
    if not isinstance(payload, list):
        raise ValueError(f"{market.upper()} OpenAPI did not return an array")
    rows = [dict(row) for row in payload if isinstance(row, dict)]
    dates = [parse_trade_date(row.get("Date")) for row in rows]
    dates = [value for value in dates if value]
    if not rows or not dates:
        raise ValueError(f"{market.upper()} OpenAPI returned no dated rows")
    source_date = Counter(dates).most_common(1)[0][0]
    rows = [row for row in rows if parse_trade_date(row.get("Date")) == source_date]
    for row in rows:
        row["Date"] = source_date
    return rows, source_date, url


def fetch_daily_quotes_exact(market: str, target_date: str) -> tuple[list[dict[str, Any]], str, str]:
    """Fetch one exact official trading date without falling back to another day.

    Historical validation must never relabel a previous close as the requested
    date.  The regular ``fetch_daily_quotes`` fallback remains appropriate for
    the site's before-close refresh, while this strict variant is used only for
    filling known dates from the official TAIEX trading calendar.
    """
    market = market.strip().lower()
    requested = parse_trade_date(target_date)
    if market not in {"twse", "tpex"}:
        raise ValueError(f"unsupported market: {market}")
    if not requested:
        raise ValueError(f"invalid target date: {target_date}")
    if market == "twse":
        rows, source_date, source_url = _twse_date_specific(requested)
    else:
        rows, source_date, source_url = _tpex_date_specific(requested)
    if source_date != requested:
        raise ValueError(f"{market.upper()} returned {source_date or '--'} for requested {requested}")
    return rows, source_date, source_url


def fetch_taiex_month(target_month: str) -> tuple[list[dict[str, Any]], str]:
    """Return official TAIEX daily OHLC bars for one Gregorian month."""
    parsed = parse_trade_date(f"{str(target_month)[:7]}-01")
    if not parsed:
        raise ValueError(f"invalid target month: {target_month}")
    compact = parsed.replace("-", "")
    url = TAIEX_MONTHLY_HISTORY + "?" + urllib.parse.urlencode(
        {"date": compact, "response": "json"}
    )
    payload = _fetch_json(url)
    if not isinstance(payload, dict) or str(payload.get("stat", "")).upper() != "OK":
        raise ValueError(f"TAIEX monthly history is unavailable for {parsed[:7]}")
    fields = payload.get("fields")
    data = payload.get("data")
    required = {"日期", "開盤指數", "最高指數", "最低指數", "收盤指數"}
    if not isinstance(fields, list) or not required.issubset(set(fields)) or not isinstance(data, list):
        raise ValueError("TAIEX monthly history is missing official OHLC fields")

    rows: list[dict[str, Any]] = []
    for values in data:
        raw = dict(zip(fields, values))
        trade_date = parse_trade_date(raw.get("日期"))
        if not trade_date or trade_date[:7] != parsed[:7]:
            continue
        rows.append(
            {
                "date": trade_date,
                "open": _clean_text(raw.get("開盤指數")),
                "high": _clean_text(raw.get("最高指數")),
                "low": _clean_text(raw.get("最低指數")),
                "close": _clean_text(raw.get("收盤指數")),
                "source": url,
            }
        )
    if not rows:
        raise ValueError(f"TAIEX monthly history returned zero rows for {parsed[:7]}")
    rows.sort(key=lambda row: row["date"])
    return rows, url


@lru_cache(maxsize=1)
def _holiday_schedule_rows() -> list[dict[str, Any]]:
    payload = _fetch_json(TWSE_HOLIDAY_SCHEDULE)
    if not isinstance(payload, list):
        raise ValueError("TWSE holiday schedule did not return an array")
    rows = [row for row in payload if isinstance(row, dict)]
    if not rows:
        raise ValueError("TWSE holiday schedule returned no rows")
    return rows


def is_official_exchange_holiday(requested: str) -> bool:
    """Return True only for an explicit official non-trading-day marker."""
    for row in _holiday_schedule_rows():
        if parse_trade_date(row.get("Date")) != requested:
            continue
        description = f"{row.get('Name') or ''} {row.get('Description') or ''}"
        if any(marker in description for marker in OPEN_MARKERS):
            return False
        if any(marker in description for marker in HOLIDAY_MARKERS):
            return True
    return False


def requires_current_trade_date(
    requested: str,
    now: datetime | None = None,
    holiday_checker: Callable[[str], bool] | None = None,
) -> bool:
    """Require today's close after the official close-data publication window.

    The 08:00 and 13:45 runs legitimately use the prior official close, as do
    weekend runs.  On a weekday after 15:20, accepting an older date would hide
    a failed current-day refresh from the 17:30/23:00 schedules.
    """
    current = now.astimezone(TAIPEI) if now is not None else datetime.now(TAIPEI)
    is_after_close_weekday = (
        requested == current.date().isoformat()
        and current.weekday() < 5
        and current.time() >= AFTER_CLOSE_CUTOFF
    )
    if not is_after_close_weekday:
        return False
    checker = holiday_checker or is_official_exchange_holiday
    try:
        return not checker(requested)
    except Exception:
        # If the official calendar cannot be checked, do not silently treat a
        # missing current-day close as a holiday.
        return True


def fetch_daily_quotes(market: str, target_date: str | None = None) -> tuple[list[dict[str, Any]], str, str]:
    """Return normalized quote rows, their real source date, and the source URL."""
    market = market.strip().lower()
    if market not in {"twse", "tpex"}:
        raise ValueError(f"unsupported market: {market}")
    requested = parse_trade_date(target_date) or datetime.now(TAIPEI).date().isoformat()
    requested_day = datetime.fromisoformat(requested).date()
    require_current = requires_current_trade_date(requested)
    failures: list[str] = []
    try:
        if market == "twse":
            return _twse_date_specific(requested)
        return _tpex_date_specific(requested)
    except Exception as primary_error:
        failures.append(f"{requested}: {primary_error}")
        if require_current:
            try:
                rows, source_date, source_url = _openapi_fallback(market)
            except Exception as fallback_error:
                raise RuntimeError(
                    f"{market.upper()} current-day quotes failed after close: "
                    f"dated={primary_error}; fallback={fallback_error}"
                ) from fallback_error
            if source_date != requested:
                raise RuntimeError(
                    f"{market.upper()} current-day quotes are not ready after close: "
                    f"requested={requested}, rolling_source_date={source_date}"
                )
            return rows, source_date, source_url
        # At 08:00, on weekends, or on exchange holidays, today's close does
        # not exist yet. Query dated official reports backwards before using
        # the lag-prone rolling OpenAPI snapshot.
        for days_back in range(1, 8):
            candidate = (requested_day - timedelta(days=days_back)).isoformat()
            try:
                if market == "twse":
                    return _twse_date_specific(candidate)
                return _tpex_date_specific(candidate)
            except Exception as candidate_error:
                failures.append(f"{candidate}: {candidate_error}")
        try:
            return _openapi_fallback(market)
        except Exception as fallback_error:
            raise RuntimeError(
                f"{market.upper()} daily quotes failed: dated={'; '.join(failures)}; fallback={fallback_error}"
            ) from fallback_error
