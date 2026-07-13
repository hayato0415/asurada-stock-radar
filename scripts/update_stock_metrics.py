#!/usr/bin/env python
"""Update daily stock quote and monthly revenue metrics.

The static front-end reads only data/processed/*.json.  This script builds a
complete per-stock metrics file from the local stock master plus public TWSE /
MOPS OpenAPI datasets.  Missing source data stays as null; zeros are reserved
for real zero values only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

try:
    import requests
except ModuleNotFoundError:  # Local Windows Python launchers may not share pip envs.
    requests = None

try:
    from official_daily_quotes import fetch_daily_quotes
except ModuleNotFoundError:  # Supports importing as scripts.update_stock_metrics in tests.
    from scripts.official_daily_quotes import fetch_daily_quotes


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"
STOCK_MASTER = DATA_DIR / "stocks_master.json"
OUTPUT = DATA_DIR / "stock_metrics_daily.json"
UPDATE_LOG = DATA_DIR / "update_log.json"

TWSE_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_MONTHLY_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TWSE_COMPANY_BASIC = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_STOCK_DAY_ALL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_MONTHLY_REVENUE = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
TPEX_COMPANY_BASIC = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

TAIPEI = timezone(timedelta(hours=8))
USER_AGENT = "ASURADA-Stock-Radar/1.0 (+https://github.com/hayato0415/asurada-stock-radar)"
MIN_QUOTE_COVERAGE_RATIO = 0.80


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s　:_：()/（）％%,-]+", "", text).lower()


def normalize_symbol(value: Any) -> str:
    match = re.search(r"\d{4,6}", str(value or ""))
    return match.group(0) if match else ""


def clean_number_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text or text in {"-", "--", "N/A", "NaN", "null", "None"}:
        return ""
    text = text.replace(",", "").replace("%", "").replace("％", "")
    text = text.replace("＋", "+").replace("－", "-").replace("−", "-")
    text = re.sub(r"[^\d.+-]", "", text)
    return text


def parse_number(value: Any) -> float | None:
    text = clean_number_text(value)
    if not text or text in {"+", "-", "."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_int(value: Any) -> int | None:
    number = parse_number(value)
    if number is None:
        return None
    return int(round(number))


def round_or_none(value: float | int | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def first_by_keywords(row: dict[str, Any], keyword_groups: list[list[str]]) -> Any:
    normalized_keys = [(normalize_text(key), value) for key, value in row.items()]
    for keywords in keyword_groups:
        needles = [normalize_text(keyword) for keyword in keywords]
        for normalized_key, value in normalized_keys:
            if all(needle in normalized_key for needle in needles):
                return value
    return None


def fetch_json(url: str) -> list[dict[str, Any]]:
    if requests is not None:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=40,
            )
        except requests.exceptions.SSLError:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=40,
                verify=False,
            )
        response.raise_for_status()
        data = response.json()
    else:
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=40) as response:
            raw = response.read()
        data = json.loads(raw.decode("utf-8-sig"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def load_stock_master(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, {})
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(f"stock master format is invalid: {path}")
    stocks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(item.get("symbol") or item.get("code") or item.get("證券代號"))
        if not symbol:
            continue
        stocks.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or item.get("stock_name") or item.get("證券名稱") or "").strip(),
                "market": str(item.get("market") or "").strip(),
            }
        )
    return stocks


def quote_market(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"上市", "twse", "listed"} or "上市" in text:
        return "twse"
    if text in {"上櫃", "tpex", "otc"} or "上櫃" in text:
        return "tpex"
    return ""


def previous_quote_counts(stocks: list[dict[str, Any]]) -> dict[str, int]:
    stock_markets = {stock["symbol"]: quote_market(stock.get("market")) for stock in stocks}
    previous = read_json(OUTPUT, {})
    items = previous.get("items", []) if isinstance(previous, dict) else []
    counts = {"twse": 0, "tpex": 0}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(item.get("symbol") or item.get("code"))
        market = stock_markets.get(symbol, "")
        if market in counts and any(item.get(key) is not None for key in ("trade_price", "change_pct", "volume")):
            counts[market] += 1
    return counts


def quote_coverage_requirements(stocks: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, int]]:
    expected_symbols: dict[str, set[str]] = {"twse": set(), "tpex": set()}
    for stock in stocks:
        market = quote_market(stock.get("market"))
        if market in expected_symbols:
            expected_symbols[market].add(stock["symbol"])

    previous_counts = previous_quote_counts(stocks)
    required = {
        market: math.ceil(max(len(symbols), previous_counts.get(market, 0)) * MIN_QUOTE_COVERAGE_RATIO)
        for market, symbols in expected_symbols.items()
    }
    return expected_symbols, required


def parse_daily_quotes(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = normalize_symbol(
            first_by_keywords(row, [["code"], ["證券", "代號"], ["股票", "代號"], ["公司", "代號"]])
        )
        if not symbol:
            continue

        close = parse_number(
            first_by_keywords(row, [["closing", "price"], ["close"], ["收盤", "價"], ["成交", "價"]])
        )
        change = parse_number(first_by_keywords(row, [["change"], ["漲跌", "價"], ["漲跌"]]))
        change_pct = parse_number(
            first_by_keywords(row, [["change", "percent"], ["漲跌", "百分"], ["漲跌", "幅"], ["漲幅"]])
        )
        if change_pct is None and close is not None and change is not None:
            previous = close - change
            if previous:
                change_pct = (change / previous) * 100

        volume = parse_int(
            first_by_keywords(row, [["trade", "volume"], ["trading", "shares"], ["成交", "股"], ["成交", "量"]])
        )
        turnover_rate = parse_number(
            first_by_keywords(row, [["turnover", "rate"], ["週轉"], ["周轉"]])
        )

        quotes[symbol] = {
            "trade_price": round_or_none(close, 2),
            "change_pct": round_or_none(change_pct, 2),
            "volume": volume,
            "turnover_rate_pct": round_or_none(turnover_rate, 2),
        }
    return quotes


def parse_revenue_month(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return ""

    compact = re.sub(r"\D", "", text)
    if len(compact) == 5:
        roc_year, month = int(compact[:3]), int(compact[3:])
        if 1 <= month <= 12:
            return f"{roc_year + 1911:04d}-{month:02d}"

    match = re.search(r"(\d{4})[/-]?(\d{1,2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"

    match = re.search(r"(\d{2,3})[/-]?(\d{1,2})", text)
    if match:
        roc_year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f"{roc_year + 1911:04d}-{month:02d}"

    return ""


def parse_monthly_revenue(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], str]:
    revenues_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = normalize_symbol(
            first_by_keywords(row, [["公司", "代號"], ["stock", "code"], ["code"]])
        )
        if not symbol:
            continue

        revenue_month = parse_revenue_month(
            first_by_keywords(row, [["資料", "年月"], ["營收", "年月"], ["revenue", "month"], ["年月"]])
        )
        revenue_raw = parse_number(
            first_by_keywords(row, [["當月", "營收"], ["營業", "收入", "當月"], ["revenue"]])
        )
        mom = parse_number(first_by_keywords(row, [["上月", "增減"], ["月", "增"], ["mom"]]))
        yoy = parse_number(first_by_keywords(row, [["去年", "同月", "增減"], ["年", "增"], ["yoy"]]))

        # MOPS monthly revenue is commonly published in thousands of TWD.
        revenue_million = round_or_none(revenue_raw / 1000, 2) if revenue_raw is not None else None
        revenues_by_symbol.setdefault(symbol, []).append(
            {
                "revenue_month": revenue_month,
                "revenue_million": revenue_million,
                "revenue_mom_pct": round_or_none(mom, 2),
                "revenue_yoy_pct": round_or_none(yoy, 2),
            }
        )

    latest_by_symbol: dict[str, dict[str, Any]] = {}
    latest_month = ""
    for symbol, entries in revenues_by_symbol.items():
        entries.sort(key=lambda item: item.get("revenue_month") or "", reverse=True)
        latest = entries[0]
        latest_by_symbol[symbol] = latest
        latest_month = max(latest_month, latest.get("revenue_month") or "")

    return latest_by_symbol, latest_month


def parse_listed_shares(rows: list[dict[str, Any]]) -> dict[str, int]:
    shares: dict[str, int] = {}
    for row in rows:
        symbol = normalize_symbol(
            first_by_keywords(row, [["公司", "代號"], ["stock", "code"], ["code"]])
        )
        if not symbol:
            continue
        share_value = first_by_keywords(
            row,
            [
                ["已發行", "普通股"],
                ["發行", "股數"],
                ["普通股", "股數"],
                ["listed", "shares"],
                ["outstanding", "shares"],
            ],
        )
        parsed = parse_int(share_value)
        if parsed and parsed > 0:
            shares[symbol] = parsed
    return shares


def safe_fetch(label: str, url: str, errors: list[str]) -> list[dict[str, Any]]:
    try:
        rows = fetch_json(url)
        print(f"{label}: fetched {len(rows)} rows")
        return rows
    except Exception as exc:  # noqa: BLE001 - report source failure, keep building.
        message = f"{label} fetch failed: {exc}"
        print(message)
        errors.append(message)
        return []


def update_log(file_name: str, updated_at: str, count: int, status: str, error: str) -> None:
    payload = read_json(UPDATE_LOG, {"updated_at": updated_at, "items": []})
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    next_items = [item for item in items if item.get("file") != file_name]
    next_items.append(
        {
            "file": file_name,
            "updated_at": updated_at,
            "count": count,
            "status": status,
            "error": error,
        }
    )
    payload = {"updated_at": updated_at, "items": next_items}
    write_json(UPDATE_LOG, payload)


def build_metrics(args: argparse.Namespace) -> dict[str, Any]:
    stocks = load_stock_master(Path(args.stock_master))
    errors: list[str] = []

    requested_date = args.date or now_taipei().date().isoformat()
    quote_rows_by_market: dict[str, list[dict[str, Any]]] = {}
    quote_dates: dict[str, str] = {}
    quote_sources: dict[str, str] = {}
    for market, label in (("twse", "TWSE daily close quotes"), ("tpex", "TPEx daily close quotes")):
        try:
            rows, source_date, source_url = fetch_daily_quotes(market, requested_date)
            quote_rows_by_market[market] = rows
            quote_dates[market] = source_date
            quote_sources[market] = source_url
            print(f"{label}: fetched {len(rows)} rows for {source_date}")
        except Exception as exc:  # noqa: BLE001 - surfaced through strict validation.
            message = f"{label} fetch failed: {exc}"
            print(message)
            errors.append(message)

    unique_quote_dates = sorted(set(quote_dates.values()))
    if len(unique_quote_dates) > 1:
        errors.append(f"Official daily quote dates do not match: {quote_dates}")
    quote_date = unique_quote_dates[0] if len(unique_quote_dates) == 1 else ""
    if not quote_date:
        errors.append("Official daily quotes have no single recognizable trade date")

    revenue_rows = (
        safe_fetch("MOPS monthly revenue listed", TWSE_MONTHLY_REVENUE, errors)
        + safe_fetch("MOPS monthly revenue OTC", TPEX_MONTHLY_REVENUE, errors)
    )
    company_rows = (
        safe_fetch("TWSE company basic", TWSE_COMPANY_BASIC, errors)
        + safe_fetch("TPEx company basic", TPEX_COMPANY_BASIC, errors)
    )

    quotes_by_market = {
        market: parse_daily_quotes(rows)
        for market, rows in quote_rows_by_market.items()
    }
    quotes = {
        **quotes_by_market.get("twse", {}),
        **quotes_by_market.get("tpex", {}),
    }
    expected_symbols, required_quote_counts = quote_coverage_requirements(stocks)
    matched_quote_counts = {
        market: len(set(quotes_by_market.get(market, {})) & symbols)
        for market, symbols in expected_symbols.items()
    }
    for market in ("twse", "tpex"):
        actual = matched_quote_counts[market]
        required = required_quote_counts[market]
        if actual < required:
            errors.append(
                f"{market.upper()} daily quote coverage {actual} is below safety threshold {required} "
                f"({MIN_QUOTE_COVERAGE_RATIO:.0%} of stock master/prior coverage)"
            )
    revenues, revenue_month = parse_monthly_revenue(revenue_rows)
    shares = parse_listed_shares(company_rows)

    now = now_taipei()
    updated_at = now.strftime("%Y-%m-%d %H:%M")
    missing_quote: list[str] = []
    missing_revenue: list[str] = []
    items: list[dict[str, Any]] = []

    for stock in stocks:
        symbol = stock["symbol"]
        quote = quotes.get(symbol, {})
        revenue = revenues.get(symbol, {})
        listed_shares = shares.get(symbol)

        trade_price = quote.get("trade_price")
        change_pct = quote.get("change_pct")
        volume = quote.get("volume")
        turnover_rate = quote.get("turnover_rate_pct")
        if turnover_rate is None and volume is not None and listed_shares:
            turnover_rate = round_or_none((volume / listed_shares) * 100, 2)

        if not quote:
            missing_quote.append(symbol)
        if not revenue:
            missing_revenue.append(symbol)

        items.append(
            {
                "symbol": symbol,
                "name": stock["name"],
                "trade_price": trade_price,
                "change_pct": change_pct,
                "volume": volume,
                "listed_shares": listed_shares,
                "turnover_rate_pct": turnover_rate,
                "revenue_million": revenue.get("revenue_million"),
                "revenue_mom_pct": revenue.get("revenue_mom_pct"),
                "revenue_yoy_pct": revenue.get("revenue_yoy_pct"),
            }
        )

    matched_quotes = len(stocks) - len(missing_quote)
    matched_revenue = len(stocks) - len(missing_revenue)
    status = "ok" if matched_quotes and matched_revenue else "partial"
    if not matched_quotes:
        status = "failed"

    payload = {
        "date": quote_date,
        "updated_at": updated_at,
        "revenue_month": revenue_month or None,
        "source": {
            "daily_quote": quote_sources,
            "monthly_revenue": "MOPS / TWSE listed revenue + TPEx OTC revenue OpenAPI",
            "listed_shares": "TWSE / TPEx company basic OpenAPI if available",
        },
        "quality": {
            "stock_master_count": len(stocks),
            "daily_quote_matched": matched_quotes,
            "daily_quote_matched_by_market": matched_quote_counts,
            "daily_quote_required_by_market": required_quote_counts,
            "daily_quote_minimum_ratio": MIN_QUOTE_COVERAGE_RATIO,
            "daily_quote_source_dates": quote_dates,
            "revenue_matched": matched_revenue,
            "missing_quote": missing_quote,
            "missing_revenue": missing_revenue,
            "errors": errors,
        },
        "items": items,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-master", default=str(STOCK_MASTER))
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    payload = build_metrics(args)
    output = Path(args.output)

    quality = payload["quality"]
    error_text = "; ".join(quality.get("errors") or [])
    if error_text or not quality.get("daily_quote_matched") or not payload.get("date"):
        print(f"stock metrics update failed; previous {output.name} preserved")
        if error_text:
            print(error_text)
        return 1

    write_json(output, payload)
    update_log(
        output.name,
        payload["updated_at"],
        len(payload["items"]),
        "ok" if quality["daily_quote_matched"] else "failed",
        error_text,
    )

    sample_2337 = next((item for item in payload["items"] if item["symbol"] == "2337"), None)
    print(
        "wrote {count} stock metrics to {path}; quotes={quotes}; revenue={revenue}".format(
            count=len(payload["items"]),
            path=output,
            quotes=quality["daily_quote_matched"],
            revenue=quality["revenue_matched"],
        )
    )
    print(f"2337: {sample_2337}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
