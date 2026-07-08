#!/usr/bin/env python
"""Build the official-data AI multi-factor score dataset.

This script is intentionally conservative:
- It reads the local stock master as the universe.
- It fetches public official TWSE / TPEx / MOPS datasets.
- It writes factor-scores.json only when enough official quote data exists.
- On source failure it writes factor-scores.status.json and preserves the
  previous successful factor-scores.json.

News is never read here and never participates in scoring.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import ssl
import statistics
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - stdlib fallback keeps local runs working.
    requests = None


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"
DOCS_DATA_DIR = ROOT / "docs" / "data" / "processed"
STOCK_MASTER = DATA_DIR / "stocks_master.json"
OUTPUT = DATA_DIR / "factor-scores.json"
STATUS_OUTPUT = DATA_DIR / "factor-scores.status.json"
META_OUTPUT = DATA_DIR / "factor-scores.meta.json"
HISTORY_OUTPUT = DATA_DIR / "factor-quote-history.json"

TAIPEI = timezone(timedelta(hours=8))
USER_AGENT = "ASURADA-Stock-Radar/2.0 (+https://github.com/hayato0415/asurada-stock-radar)"

TWSE_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_VALUATION = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TWSE_MONTHLY_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TWSE_COMPANY_BASIC = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"

TPEX_DAILY_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_VALUATION = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TPEX_MONTHLY_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_O"
TPEX_COMPANY_BASIC = "https://openapi.twse.com.tw/v1/opendata/t187ap03_O"

WEIGHTS = {
    "fundamentalScore": 0.30,
    "technicalScore": 0.30,
    "chipScore": 0.25,
    "turnoverScore": 0.15,
}

EXCLUDED_NAME_KEYWORDS = (
    "ETF",
    "ETN",
    "指數",
    "指數投資證券",
    "受益證券",
    "認購",
    "認售",
    "權證",
    "牛證",
    "熊證",
    "特別股",
    "可轉債",
    "債",
)

EXCLUDED_NAME_KEYWORDS = (
    "ETF",
    "ETN",
    "指數",
    "指數投資證券",
    "受益證券",
    "認購",
    "認售",
    "權證",
    "牛證",
    "熊證",
    "特別股",
    "可轉債",
    "債",
)

FACTOR_NEWS_EXCLUSION_REASON = "新聞面不納入分數、不納入排名、不作為篩選條件。"


SOURCE_NAME_MAP = {
    TWSE_STOCK_DAY_ALL: "TWSE 上市每日行情",
    TPEX_DAILY_QUOTES: "TPEx 上櫃每日行情",
    TWSE_VALUATION: "TWSE 上市本益比殖利率",
    TPEX_VALUATION: "TPEx 上櫃本益比殖利率",
    TWSE_MONTHLY_REVENUE: "MOPS 上市月營收",
    TPEX_MONTHLY_REVENUE: "MOPS 上櫃月營收",
    TWSE_COMPANY_BASIC: "MOPS 上市公司基本資料",
    TPEX_COMPANY_BASIC: "MOPS 上櫃公司基本資料",
}


def clean_source_name(name: str, url: str) -> str:
    return SOURCE_NAME_MAP.get(url, name)


@dataclass
class SourceStatus:
    name: str
    url: str
    ok: bool = False
    http_status: int | None = None
    source_date: str | None = None
    row_count: int = 0
    error: str = ""
    required_fields_missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": clean_source_name(self.name, self.url),
            "url": self.url,
            "ok": self.ok,
            "http_status": self.http_status,
            "source_date": self.source_date,
            "row_count": self.row_count,
            "error": self.error,
            "required_fields_missing": self.required_fields_missing,
        }


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def iso_now() -> str:
    return now_taipei().replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def mirror_factor_output_to_docs(path: Path, text: str) -> None:
    """Keep GitHub Pages docs/ data in sync with root processed factor data."""
    try:
        relative = path.relative_to(DATA_DIR)
    except ValueError:
        return
    if not relative.name.startswith("factor-"):
        return
    mirror_path = DOCS_DATA_DIR / relative
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    mirror_factor_output_to_docs(path, text)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s\u3000:_：()/（）％%,-]+", "", text).lower()


def normalize_symbol(value: Any) -> str:
    match = re.search(r"\d{4,6}", str(value or ""))
    return match.group(0) if match else ""


def clean_number_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text or text in {"-", "--", "N/A", "NaN", "null", "None", "除權息"}:
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


def parse_roc_or_iso_date(value: Any) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return None

    match = re.search(r"(\d{4})[-/年]?(\d{1,2})[-/月]?(\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    compact = re.sub(r"\D", "", text)
    if len(compact) == 7:
        year = int(compact[:3]) + 1911
        month = int(compact[3:5])
        day = int(compact[5:7])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    if len(compact) == 8:
        year = int(compact[:4])
        month = int(compact[4:6])
        day = int(compact[6:8])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def parse_revenue_month(value: Any) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return None
    compact = re.sub(r"\D", "", text)
    if len(compact) == 5:
        year, month = int(compact[:3]) + 1911, int(compact[3:])
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    match = re.search(r"(\d{4})[/-]?(\d{1,2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    match = re.search(r"(\d{2,3})[/-]?(\d{1,2})", text)
    if match:
        year, month = int(match.group(1)) + 1911, int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    return None


def fetch_rows(name: str, url: str) -> tuple[list[dict[str, Any]], SourceStatus]:
    status = SourceStatus(name=name, url=url)
    def fetch_with_urllib(ignore_ssl: bool = False) -> tuple[Any, int]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"},
        )
        context = ssl._create_unverified_context() if ignore_ssl else None  # noqa: SLF001
        with urllib.request.urlopen(request, timeout=45, context=context) as response:  # noqa: S310 - official HTTPS sources.
            raw = response.read().decode("utf-8-sig")
            return json.loads(raw), response.status

    try:
        if requests is not None:
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"},
                    timeout=45,
                )
                status.http_status = response.status_code
                response.raise_for_status()
                data = response.json()
            except Exception:
                # Some TPEx official OpenAPI hosts fail certificate validation
                # in bundled Python builds. Retry the same official URL through
                # urllib so a local CA quirk does not become a false data miss.
                data, http_status = fetch_with_urllib(ignore_ssl="tpex.org.tw" in url)
                status.http_status = http_status
        else:
            data, http_status = fetch_with_urllib(ignore_ssl="tpex.org.tw" in url)
            status.http_status = http_status
        if isinstance(data, list):
            rows = [row for row in data if isinstance(row, dict)]
        elif isinstance(data, dict):
            rows = []
            for key in ("data", "items", "result"):
                if isinstance(data.get(key), list):
                    rows = [row for row in data[key] if isinstance(row, dict)]
                    break
        else:
            rows = []
        status.ok = bool(rows)
        status.row_count = len(rows)
        if not rows:
            status.error = "資料來源回傳空資料"
        return rows, status
    except Exception as exc:  # noqa: BLE001 - convert to status JSON.
        status.ok = False
        status.error = str(exc)
        return [], status


def load_stock_master() -> list[dict[str, Any]]:
    payload = read_json(STOCK_MASTER, {})
    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise ValueError(f"股票主檔格式錯誤：{STOCK_MASTER}")

    stocks: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(item.get("symbol") or item.get("code") or item.get("股票代號"))
        name = str(item.get("name") or item.get("stock_name") or item.get("股票名稱") or "").strip()
        if not symbol or not name:
            continue
        if not re.fullmatch(r"\d{4}", symbol):
            continue
        if any(keyword in name for keyword in EXCLUDED_NAME_KEYWORDS):
            continue
        stocks.append(
            {
                "symbol": symbol,
                "name": name,
                "market": str(item.get("market") or "").strip(),
                "industry": str(item.get("industry") or "").strip(),
                "concepts": [x for x in [item.get("theme"), item.get("supply_chain")] if x],
            }
        )
    return stocks


def parse_quote_rows(rows: list[dict[str, Any]], market_label: str) -> tuple[dict[str, dict[str, Any]], str | None]:
    quotes: dict[str, dict[str, Any]] = {}
    dates: list[str] = []
    for row in rows:
        symbol = normalize_symbol(
            first_by_keywords(row, [["code"], ["證券", "代號"], ["股票", "代號"], ["公司", "代號"]])
        )
        if not symbol:
            continue

        source_date = parse_roc_or_iso_date(
            first_by_keywords(row, [["date"], ["資料", "日期"], ["年月日"], ["交易", "日期"]])
        )
        if source_date:
            dates.append(source_date)

        name = str(first_by_keywords(row, [["name"], ["證券", "名稱"], ["股票", "名稱"], ["公司", "名稱"]]) or "").strip()
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
        trade_value = parse_number(
            first_by_keywords(row, [["trade", "value"], ["成交", "金額"], ["成交", "值"]])
        )
        turnover_rate = parse_number(first_by_keywords(row, [["turnover", "rate"], ["週轉"], ["周轉"]]))

        quotes[symbol] = {
            "symbol": symbol,
            "name": name,
            "market": market_label,
            "trade_price": round_or_none(close, 2),
            "change_pct": round_or_none(change_pct, 2),
            "volume": volume,
            "trade_value": round_or_none(trade_value, 0),
            "turnover_rate_pct": round_or_none(turnover_rate, 4),
            "source_date": source_date,
        }
    source_date = statistics.mode(dates) if dates else None
    return quotes, source_date


def parse_valuation_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    valuations: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = normalize_symbol(
            first_by_keywords(row, [["code"], ["證券", "代號"], ["股票", "代號"], ["公司", "代號"]])
        )
        if not symbol:
            continue
        valuations[symbol] = {
            "pe_ratio": round_or_none(parse_number(first_by_keywords(row, [["pe"], ["本益比"]])), 2),
            "pb_ratio": round_or_none(parse_number(first_by_keywords(row, [["pb"], ["股價", "淨值比"], ["淨值比"]])), 2),
            "dividend_yield": round_or_none(parse_number(first_by_keywords(row, [["dividend", "yield"], ["殖利率"]])), 2),
        }
    return valuations


def parse_monthly_revenue(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], str | None]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    months: list[str] = []
    for row in rows:
        symbol = normalize_symbol(
            first_by_keywords(row, [["公司", "代號"], ["stock", "code"], ["code"]])
        )
        if not symbol:
            continue
        month = parse_revenue_month(
            first_by_keywords(row, [["資料", "年月"], ["營收", "年月"], ["revenue", "month"], ["年月"]])
        )
        revenue = parse_number(
            first_by_keywords(row, [["當月", "營收"], ["營業", "收入", "當月"], ["revenue"]])
        )
        mom = parse_number(first_by_keywords(row, [["上月", "比較", "增減"], ["月增"], ["mom"]]))
        yoy = parse_number(first_by_keywords(row, [["去年", "同月", "增減"], ["年增"], ["yoy"]]))
        if month:
            months.append(month)
        by_symbol.setdefault(symbol, []).append(
            {
                "revenue_month": month,
                "revenue_million": round_or_none(revenue / 1000 if revenue is not None else None, 2),
                "revenue_mom_pct": round_or_none(mom, 2),
                "revenue_yoy_pct": round_or_none(yoy, 2),
            }
        )

    latest_month = max(months) if months else None
    latest: dict[str, dict[str, Any]] = {}
    for symbol, values in by_symbol.items():
        values.sort(key=lambda item: item.get("revenue_month") or "")
        latest[symbol] = values[-1]
    return latest, latest_month


def parse_company_basic(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    basics: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = normalize_symbol(first_by_keywords(row, [["公司", "代號"], ["stock", "code"], ["code"]]))
        if not symbol:
            continue
        shares = parse_number(
            first_by_keywords(
                row,
                [
                    ["已發行", "普通股"],
                    ["普通股", "股數"],
                    ["發行", "股數"],
                    ["實收", "資本"],
                    ["capital"],
                ],
            )
        )
        # Some official basic endpoints expose paid-in capital in NTD, not shares.
        # If the parsed number looks like capital dollars, divide by 10.
        listed_shares = None
        if shares is not None:
            listed_shares = int(round(shares / 10)) if shares > 100_000_000_000 else int(round(shares))
        basics[symbol] = {"listed_shares": listed_shares}
    return basics


def merge_source_status(source_status: list[SourceStatus], quotes: dict[str, dict[str, Any]]) -> str | None:
    dates = [quote.get("source_date") for quote in quotes.values() if quote.get("source_date")]
    latest_trade_date = max(dates) if dates else None
    for status in source_status:
        if "行情" in status.name and not status.source_date:
            market = "上市" if "TWSE" in status.name else "上櫃"
            market_dates = [
                quote.get("source_date")
                for quote in quotes.values()
                if quote.get("market") == market and quote.get("source_date")
            ]
            if market_dates:
                status.source_date = max(market_dates)
    return latest_trade_date


def update_history(
    existing: dict[str, Any],
    quote_date: str,
    quote_items: dict[str, dict[str, Any]],
    force_refresh: bool = False,
) -> dict[str, Any]:
    history_items: dict[str, list[dict[str, Any]]] = {}
    if not force_refresh and isinstance(existing.get("items"), dict):
        history_items = {
            str(symbol): list(values)
            for symbol, values in existing["items"].items()
            if isinstance(values, list)
        }

    for symbol, quote in quote_items.items():
        if quote.get("trade_price") is None:
            continue
        series = [item for item in history_items.get(symbol, []) if item.get("date") != quote_date]
        series.append(
            {
                "date": quote_date,
                "close": quote.get("trade_price"),
                "change_pct": quote.get("change_pct"),
                "volume": quote.get("volume"),
                "trade_value": quote.get("trade_value"),
                "turnover_rate_pct": quote.get("turnover_rate_pct"),
            }
        )
        series.sort(key=lambda item: item.get("date") or "")
        history_items[symbol] = series[-80:]

    return {"updated_at": iso_now(), "items": history_items}


def percentile(value: float | None, values: list[float]) -> float | None:
    if value is None or not values:
        return None
    sorted_values = sorted(values)
    below = sum(1 for item in sorted_values if item <= value)
    return below / len(sorted_values)


def score_from_percentile(value: float | None, values: list[float], floor: float = 15, ceiling: float = 95) -> float | None:
    rank = percentile(value, values)
    if rank is None:
        return None
    return round(floor + rank * (ceiling - floor), 1)


def fundamental_score(valuation: dict[str, Any], revenue: dict[str, Any]) -> float | None:
    parts: list[float] = []
    pe = valuation.get("pe_ratio")
    pb = valuation.get("pb_ratio")
    div_yield = valuation.get("dividend_yield")
    yoy = revenue.get("revenue_yoy_pct")
    mom = revenue.get("revenue_mom_pct")

    if pe is not None and pe > 0:
        if pe <= 12:
            parts.append(82)
        elif pe <= 20:
            parts.append(74)
        elif pe <= 35:
            parts.append(62)
        else:
            parts.append(45)
    if pb is not None and pb > 0:
        if pb <= 1.2:
            parts.append(76)
        elif pb <= 2.5:
            parts.append(66)
        elif pb <= 5:
            parts.append(55)
        else:
            parts.append(42)
    if div_yield is not None:
        parts.append(max(35, min(82, 45 + div_yield * 7)))
    if yoy is not None:
        parts.append(max(20, min(92, 55 + yoy * 0.7)))
    if mom is not None:
        parts.append(max(25, min(86, 55 + mom * 0.8)))

    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


def technical_score(quote: dict[str, Any], series: list[dict[str, Any]]) -> float | None:
    change_pct = quote.get("change_pct")
    close = quote.get("trade_price")
    if change_pct is None or close is None:
        return None
    score = 52 + max(-18, min(18, change_pct * 3))
    closes = [item.get("close") for item in series if isinstance(item.get("close"), (int, float))]
    if len(closes) >= 5:
        ma5 = sum(closes[-5:]) / 5
        score += 8 if close >= ma5 else -5
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
        score += 10 if close >= ma20 else -8
    if len(closes) >= 60:
        high60 = max(closes[-60:])
        low60 = min(closes[-60:])
        if high60 and close >= high60 * 0.95:
            score += 8
        if low60 and close <= low60 * 1.10:
            score -= 5
    return round(max(0, min(100, score)), 1)


def chip_score(quote: dict[str, Any], series: list[dict[str, Any]], trade_value_pool: list[float]) -> float | None:
    volume = quote.get("volume")
    trade_value = quote.get("trade_value")
    if volume is None and trade_value is None:
        return None
    score = 45.0
    value_score = score_from_percentile(trade_value, trade_value_pool, 25, 88)
    if value_score is not None:
        score = value_score
    volumes = [item.get("volume") for item in series[:-1] if isinstance(item.get("volume"), (int, float)) and item.get("volume") > 0]
    if volume is not None and volumes:
        avg_volume = sum(volumes[-20:]) / min(20, len(volumes))
        if avg_volume > 0:
            volume_ratio = volume / avg_volume
            score += max(-12, min(18, (volume_ratio - 1) * 12))
    return round(max(0, min(100, score)), 1)


def classify_trade_type(total: float, tech: float | None, turnover: float | None) -> str:
    if total >= 78 and turnover is not None and turnover >= 75:
        return "短線"
    if tech is not None and tech >= 68:
        return "波段"
    return "中長期"


def classify_risk(quote: dict[str, Any], turnover_score: float | None, chip: float | None) -> str:
    change_pct = quote.get("change_pct")
    volume = quote.get("volume")
    turnover = quote.get("turnover_rate_pct")
    if turnover_score is not None and turnover_score >= 92:
        return "過熱"
    if change_pct is not None and change_pct >= 7:
        return "過熱"
    if volume is not None and volume < 100_000:
        return "低流動"
    if turnover is not None and turnover < 0.05:
        return "低流動"
    if chip is not None and chip < 35:
        return "冷門"
    return "正常"


def build_scores(
    stocks: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    valuations: dict[str, dict[str, Any]],
    revenues: dict[str, dict[str, Any]],
    basics: dict[str, dict[str, Any]],
    history: dict[str, Any],
    latest_trade_date: str,
    revenue_month: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    history_items = history.get("items", {}) if isinstance(history.get("items"), dict) else {}
    trade_values = [
        quote.get("trade_value")
        for quote in quotes.values()
        if isinstance(quote.get("trade_value"), (int, float)) and quote.get("trade_value") > 0
    ]

    # TWSE daily quotes do not always include turnover rate. Compute it once
    # before building the percentile pool so the turnover factor can rank the
    # whole market instead of excluding every stock.
    for stock in stocks:
        symbol = stock["symbol"]
        quote = quotes.get(symbol)
        if not quote:
            continue
        listed_shares = basics.get(symbol, {}).get("listed_shares")
        if quote.get("turnover_rate_pct") is None and quote.get("volume") is not None and listed_shares:
            quote["turnover_rate_pct"] = round((quote["volume"] / listed_shares) * 100, 4)

    turnover_values = [
        quote.get("turnover_rate_pct")
        for quote in quotes.values()
        if isinstance(quote.get("turnover_rate_pct"), (int, float)) and quote.get("turnover_rate_pct") >= 0
    ]

    rows: list[dict[str, Any]] = []
    missing_quote: list[str] = []
    missing_score: list[str] = []

    for stock in stocks:
        symbol = stock["symbol"]
        quote = dict(quotes.get(symbol) or {})
        if not quote:
            missing_quote.append(symbol)
            continue
        valuation = valuations.get(symbol, {})
        revenue = revenues.get(symbol, {})
        basic = basics.get(symbol, {})

        listed_shares = basic.get("listed_shares")

        series = list(history_items.get(symbol, []))
        fundamental = fundamental_score(valuation, revenue)
        technical = technical_score(quote, series)
        chip = chip_score(quote, series, trade_values)
        turnover = score_from_percentile(quote.get("turnover_rate_pct"), turnover_values, 20, 95)

        score_parts = [fundamental, technical, chip, turnover]
        if any(part is None for part in score_parts):
            missing_score.append(symbol)
            continue

        total = round(
            fundamental * WEIGHTS["fundamentalScore"]
            + technical * WEIGHTS["technicalScore"]
            + chip * WEIGHTS["chipScore"]
            + turnover * WEIGHTS["turnoverScore"],
            1,
        )
        name = quote.get("name") or stock.get("name") or symbol
        concepts = list(dict.fromkeys([value for value in stock.get("concepts", []) if value]))
        row = {
            "code": symbol,
            "symbol": symbol,
            "name": name,
            "market": quote.get("market") or stock.get("market") or "",
            "industry": stock.get("industry") or "",
            "concepts": concepts,
            "close": quote.get("trade_price"),
            "changePercent": quote.get("change_pct"),
            "volume": quote.get("volume"),
            "tradeValue": quote.get("trade_value"),
            "listedShares": listed_shares,
            "turnoverRate": quote.get("turnover_rate_pct"),
            "peRatio": valuation.get("pe_ratio"),
            "pbRatio": valuation.get("pb_ratio"),
            "dividendYield": valuation.get("dividend_yield"),
            "revenueMonth": revenue.get("revenue_month") or revenue_month,
            "revenueMillion": revenue.get("revenue_million"),
            "revenueMomPct": revenue.get("revenue_mom_pct"),
            "revenueYoyPct": revenue.get("revenue_yoy_pct"),
            "fundamentalScore": fundamental,
            "technicalScore": technical,
            "chipScore": chip,
            "turnoverScore": turnover,
            "totalScore": total,
            "tradeType": classify_trade_type(total, technical, turnover),
            "riskLabel": classify_risk(quote, turnover, chip),
            "updatedAt": iso_now(),
            "dataDate": latest_trade_date,
            "scoreSource": "official_quote_valuation_revenue",
        }
        rows.append(row)

    rows.sort(key=lambda item: item["totalScore"], reverse=True)
    for index, row in enumerate(rows[:100], start=1):
        row["rank"] = index

    quality = {
        "stock_master_count": len(stocks),
        "quote_matched": len(quotes),
        "score_candidates": len(rows),
        "missing_quote_count": len(missing_quote),
        "missing_score_count": len(missing_score),
        "missing_quote_sample": missing_quote[:50],
        "missing_score_sample": missing_score[:50],
    }
    return rows[:100], quality


def write_failure_status(
    *,
    target_date: str | None,
    attempted_at: str,
    source_status: list[SourceStatus],
    failed_reasons: list[str],
    warnings: list[str],
) -> None:
    previous_items = get_items(read_json(OUTPUT, []))
    payload = {
        "ok": False,
        "updated_at": attempted_at,
        "attempted_at": attempted_at,
        "target_date": target_date,
        "latest_trade_date": None,
        "items_count": len(previous_items),
        "rows_written": 0,
        "stock_master_count": None,
        "twse_quote_matched": 0,
        "tpex_quote_matched": 0,
        "previous_data_preserved": True,
        "failed_reasons": failed_reasons,
        "warnings": warnings,
        "official_source_used": {
            "daily_quotes": "TWSE STOCK_DAY_ALL / TPEx daily close quotes",
            "valuation": "TWSE BWIBBU_ALL / TPEx peratio analysis",
            "monthly_revenue": "MOPS t187ap05_L / t187ap05_O",
            "company_basic": "MOPS t187ap03_L / t187ap03_O",
        },
        "source_status": [status.as_dict() for status in source_status],
        "outputs": {
            "factor-scores.json": "preserved",
            "factor-scores.status.json": "updated",
        },
    }
    write_json(STATUS_OUTPUT, payload)


def get_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    return []


def run(target_date: str | None, force_history_refresh: bool) -> int:
    attempted_at = iso_now()
    source_status: list[SourceStatus] = []
    warnings: list[str] = []
    failed_reasons: list[str] = []

    stocks = load_stock_master()

    twse_quote_rows, twse_quote_status = fetch_rows("TWSE 上市每日行情", TWSE_STOCK_DAY_ALL)
    tpex_quote_rows, tpex_quote_status = fetch_rows("TPEx 上櫃每日行情", TPEX_DAILY_QUOTES)
    twse_val_rows, twse_val_status = fetch_rows("TWSE 上市本益比殖利率", TWSE_VALUATION)
    tpex_val_rows, tpex_val_status = fetch_rows("TPEx 上櫃本益比殖利率", TPEX_VALUATION)
    twse_rev_rows, twse_rev_status = fetch_rows("MOPS 上市月營收", TWSE_MONTHLY_REVENUE)
    tpex_rev_rows, tpex_rev_status = fetch_rows("MOPS 上櫃月營收", TPEX_MONTHLY_REVENUE)
    twse_basic_rows, twse_basic_status = fetch_rows("MOPS 上市公司基本資料", TWSE_COMPANY_BASIC)
    tpex_basic_rows, tpex_basic_status = fetch_rows("MOPS 上櫃公司基本資料", TPEX_COMPANY_BASIC)
    source_status.extend(
        [
            twse_quote_status,
            tpex_quote_status,
            twse_val_status,
            tpex_val_status,
            twse_rev_status,
            tpex_rev_status,
            twse_basic_status,
            tpex_basic_status,
        ]
    )

    twse_quotes, twse_date = parse_quote_rows(twse_quote_rows, "上市")
    tpex_quotes, tpex_date = parse_quote_rows(tpex_quote_rows, "上櫃")
    twse_quote_status.source_date = twse_date
    tpex_quote_status.source_date = tpex_date

    universe_symbols = {stock["symbol"] for stock in stocks}
    twse_quotes = {symbol: quote for symbol, quote in twse_quotes.items() if symbol in universe_symbols}
    tpex_quotes = {symbol: quote for symbol, quote in tpex_quotes.items() if symbol in universe_symbols}
    quotes = {**twse_quotes, **tpex_quotes}
    latest_trade_date = merge_source_status(source_status, quotes)

    if not twse_quote_status.ok:
        failed_reasons.append(f"TWSE 行情來源失敗：{twse_quote_status.error or '無資料'}")
    if not tpex_quote_status.ok:
        warnings.append(f"TPEx 行情來源失敗：{tpex_quote_status.error or '無資料'}")
    if not latest_trade_date:
        failed_reasons.append("官方行情來源沒有可辨識的交易日期")
    if target_date and latest_trade_date and latest_trade_date != target_date:
        failed_reasons.append(f"行情資料日期 {latest_trade_date} 與指定 target_date {target_date} 不一致")

    if failed_reasons:
        write_failure_status(
            target_date=target_date,
            attempted_at=attempted_at,
            source_status=source_status,
            failed_reasons=failed_reasons,
            warnings=warnings,
        )
        print("factor score update failed; previous factor-scores.json preserved")
        for reason in failed_reasons:
            print(f"- {reason}")
        return 0

    valuations = {**parse_valuation_rows(twse_val_rows), **parse_valuation_rows(tpex_val_rows)}
    twse_revenue, twse_revenue_month = parse_monthly_revenue(twse_rev_rows)
    tpex_revenue, tpex_revenue_month = parse_monthly_revenue(tpex_rev_rows)
    revenues = {**twse_revenue, **tpex_revenue}
    revenue_months = [month for month in [twse_revenue_month, tpex_revenue_month] if month]
    revenue_month = max(revenue_months) if revenue_months else None
    basics = {**parse_company_basic(twse_basic_rows), **parse_company_basic(tpex_basic_rows)}

    existing_history = read_json(HISTORY_OUTPUT, {})
    history = update_history(existing_history, latest_trade_date or target_date or "", quotes, force_history_refresh)
    rows, quality = build_scores(stocks, quotes, valuations, revenues, basics, history, latest_trade_date or "", revenue_month)

    if not rows:
        write_failure_status(
            target_date=target_date,
            attempted_at=attempted_at,
            source_status=source_status,
            failed_reasons=["可排名股票為 0，未覆蓋上一版 factor-scores.json"],
            warnings=warnings,
        )
        print("factor score update produced zero ranked rows; previous factor-scores.json preserved")
        return 0

    write_json(OUTPUT, rows)
    write_json(HISTORY_OUTPUT, history)

    status_payload = {
        "ok": True,
        "updated_at": attempted_at,
        "attempted_at": attempted_at,
        "target_date": target_date or latest_trade_date,
        "latest_trade_date": latest_trade_date,
        "revenue_month": revenue_month,
        "items_count": len(rows),
        "rows_written": len(rows),
        "stock_master_count": len(stocks),
        "twse_quote_matched": len(twse_quotes),
        "tpex_quote_matched": len(tpex_quotes),
        "previous_data_preserved": False,
        "failed_reasons": [],
        "warnings": warnings,
        "official_source_used": {
            "daily_quotes": "TWSE STOCK_DAY_ALL / TPEx daily close quotes",
            "valuation": "TWSE BWIBBU_ALL / TPEx peratio analysis",
            "monthly_revenue": "MOPS t187ap05_L / t187ap05_O",
            "company_basic": "MOPS t187ap03_L / t187ap03_O",
        },
        "quality": quality,
        "source_status": [status.as_dict() for status in source_status],
        "outputs": {
            "factor-scores.json": "updated",
            "factor-scores.status.json": "updated",
            "factor-scores.meta.json": "updated",
            "factor-quote-history.json": "updated",
        },
    }
    write_json(STATUS_OUTPUT, status_payload)
    meta_payload = {
        "updated_at": attempted_at,
        "latest_trade_date": latest_trade_date,
        "revenue_month": revenue_month,
        "score_version": "official-multifactor-v1",
        "weights": WEIGHTS,
        "news_score": {
            "weight": 0,
            "included": False,
            "reason": "新聞面不納入分數、不納入排名、不作為篩選條件。",
        },
        "sources": {
            "daily_quotes": ["TWSE STOCK_DAY_ALL", "TPEx daily close quotes"],
            "valuation": ["TWSE BWIBBU_ALL", "TPEx peratio analysis"],
            "monthly_revenue": ["MOPS / TWSE OpenAPI t187ap05_L", "MOPS / TWSE OpenAPI t187ap05_O"],
            "company_basic": ["MOPS / TWSE OpenAPI t187ap03_L", "MOPS / TWSE OpenAPI t187ap03_O"],
        },
    }
    meta_payload["news_score"]["reason"] = FACTOR_NEWS_EXCLUSION_REASON
    write_json(META_OUTPUT, meta_payload)

    print(f"factor scores updated: {len(rows)} rows")
    print(f"latest trade date: {latest_trade_date}")
    for row in rows[:10]:
        print(f"#{row['rank']} {row['code']} {row['name']} {row['totalScore']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Update official-data factor scores.")
    parser.add_argument("--target-date", help="Expected market date, YYYY-MM-DD. If omitted, latest official quote date is used.")
    parser.add_argument("--force-history-refresh", action="store_true", help="Rebuild quote history from the current snapshot only.")
    args = parser.parse_args()
    return run(args.target_date, args.force_history_refresh)


if __name__ == "__main__":
    raise SystemExit(main())
