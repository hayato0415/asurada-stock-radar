from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
ARCHIVE_DIR = DOCS_DATA / "archive"
TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")
NEWS_FETCH_STATUS: dict = {}
QUOTE_REFRESH_STATUS: dict = {}

STAGES = {
    "premarket": {
        "label": "盤前更新",
        "schedule_time": "08:07",
        "targets": ["market", "news"],
    },
    "intraday": {
        "label": "盤中更新",
        "schedule_time": "11:07",
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


def clean_cell(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("\xa0", " ").strip()


def parse_float(value):
    text = clean_cell(value).replace(",", "").replace("%", "").replace("億", "").replace("張", "")
    if text in {"", "-", "--", "---", "除權息"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value):
    number = parse_float(value)
    return int(round(number)) if number is not None else None


def request_json(url: str):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 asurada-stock-radar/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read()
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        # Some Windows Python installs reject TWSE's certificate chain.
        # This is only used for public quote JSON; never for private data.
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=25, context=context) as response:
            raw = response.read()
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return json.loads(raw.decode(encoding))
        except Exception:
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def find_field(fields: list[str], keywords: list[str]) -> int | None:
    cleaned = [clean_cell(field) for field in fields]
    for keyword in keywords:
        for index, field in enumerate(cleaned):
            if keyword in field:
                return index
    return None


def normalize_change(sign_value, change_value) -> float | None:
    change = parse_float(change_value)
    if change is None:
        return None
    sign = clean_cell(sign_value)
    if "-" in sign or "－" in sign or "跌" in sign:
        return -abs(change)
    if "+" in sign or "＋" in sign or "漲" in sign:
        return abs(change)
    return change


def quote_percent(close: float | None, change: float | None) -> float | None:
    if close is None or change is None:
        return None
    previous = close - change
    if previous == 0:
        return None
    return round(change / previous * 100, 2)


def twse_quote_url(date_text: str) -> str:
    query = urlencode({"date": date_text, "type": "ALLBUT0999", "response": "json"})
    return f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?{query}"


def tpex_quote_urls(date: datetime) -> list[str]:
    gregorian = date.strftime("%Y/%m/%d")
    roc = f"{date.year - 1911}/{date.month:02d}/{date.day:02d}"
    return [
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?"
        + urlencode({"date": gregorian, "type": "EW", "response": "json"}),
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?"
        + urlencode({"date": roc, "type": "EW", "response": "json"}),
        "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?"
        + urlencode({"l": "zh-tw", "o": "json", "d": roc, "s": "0,asc,0"}),
    ]


def parse_quote_tables(payload: dict, trade_date: str, source: str) -> dict[str, dict]:
    quotes: dict[str, dict] = {}
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        tables = []
    if isinstance(payload, dict) and isinstance(payload.get("aaData"), list):
        tables.append({"fields": payload.get("fields") or [], "data": payload.get("aaData")})
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        tables.append({"fields": payload.get("fields") or [], "data": payload.get("data")})

    for table in tables:
        fields = [clean_cell(field) for field in (table.get("fields") or [])]
        rows = table.get("data") or table.get("aaData") or []
        if not isinstance(rows, list):
            continue
        code_idx = find_field(fields, ["證券代號", "代號", "股票代號"])
        name_idx = find_field(fields, ["證券名稱", "名稱", "股票名稱"])
        volume_idx = find_field(fields, ["成交股數", "成交股", "成交量"])
        close_idx = find_field(fields, ["收盤價", "收盤"])
        sign_idx = find_field(fields, ["漲跌(+/-)", "漲跌(+／-)", "漲跌"])
        change_idx = find_field(fields, ["漲跌價差", "漲跌"])

        for row in rows:
            if not isinstance(row, list):
                continue
            fallback_code = clean_cell(row[0]) if row else ""
            code = clean_cell(row[code_idx]) if code_idx is not None and code_idx < len(row) else fallback_code
            if not re.fullmatch(r"\d{4}", code):
                continue
            name = clean_cell(row[name_idx]) if name_idx is not None and name_idx < len(row) else ""
            close = parse_float(row[close_idx]) if close_idx is not None and close_idx < len(row) else None
            volume_raw = row[volume_idx] if volume_idx is not None and volume_idx < len(row) else None
            volume = parse_float(volume_raw)
            if source == "TWSE" and volume is not None:
                volume = round(volume / 1000)
            change = normalize_change(
                row[sign_idx] if sign_idx is not None and sign_idx < len(row) else "",
                row[change_idx] if change_idx is not None and change_idx < len(row) else None,
            )
            if close is None and volume is None and change is None:
                continue
            quotes[code] = {
                "code": code,
                "name": name,
                "close": close,
                "price_change": change,
                "change_percent": quote_percent(close, change),
                "volume": int(volume) if volume is not None else None,
                "market_date": trade_date,
                "source": source,
            }
    return quotes


def fetch_official_quotes(current: datetime, lookback_days: int = 10) -> tuple[dict[str, dict], dict]:
    errors: list[str] = []
    for offset in range(lookback_days + 1):
        date = current - timedelta(days=offset)
        date_ymd = date.strftime("%Y%m%d")
        trade_date = date.strftime("%Y-%m-%d")
        quotes: dict[str, dict] = {}

        try:
            twse_payload = request_json(twse_quote_url(date_ymd))
            twse_quotes = parse_quote_tables(twse_payload, trade_date, "TWSE")
            quotes.update(twse_quotes)
        except Exception as exc:
            errors.append(f"TWSE {trade_date}: {exc}")

        for url in tpex_quote_urls(date):
            try:
                tpex_payload = request_json(url)
                tpex_quotes = parse_quote_tables(tpex_payload, trade_date, "TPEX")
                if tpex_quotes:
                    quotes.update(tpex_quotes)
                    break
            except Exception as exc:
                errors.append(f"TPEX {trade_date}: {exc}")

        if quotes:
            return quotes, {
                "success": True,
                "market_date": trade_date,
                "quote_count": len(quotes),
                "source": "TWSE/TPEX official quote",
                "errors": errors[-5:],
            }
    return {}, {
        "success": False,
        "market_date": "",
        "quote_count": 0,
        "source": "TWSE/TPEX official quote",
        "errors": errors[-10:],
        "error": "No official quote rows fetched; kept previous stock quote data.",
    }


def apply_quotes_to_stocks(items: list[dict], quotes: dict[str, dict], updated_at: str) -> tuple[list[dict], int]:
    updated_items: list[dict] = []
    updated_count = 0
    for item in items:
        if not isinstance(item, dict):
            updated_items.append(item)
            continue
        code = str(item.get("code") or "").strip()
        quote = quotes.get(code)
        if not quote:
            updated_items.append(item)
            continue
        refreshed = dict(item)
        close = quote.get("close")
        price_change = quote.get("price_change")
        change_percent = quote.get("change_percent")
        volume = quote.get("volume")
        if close is not None:
            refreshed["close"] = f"{close:.2f}".rstrip("0").rstrip(".")
            refreshed["close_price"] = close
        if price_change is not None:
            refreshed["price_change"] = round(price_change, 2)
        if change_percent is not None:
            refreshed["change_percent"] = round(change_percent, 2)
            if price_change is not None:
                refreshed["daily_change"] = f"{price_change:+.2f} ({change_percent:+.2f}%)"
            else:
                refreshed["daily_change"] = f"{change_percent:+.2f}%"
        if volume is not None:
            refreshed["volume"] = str(volume)
            refreshed["volume_value"] = float(volume)
        refreshed["market_date"] = quote.get("market_date")
        refreshed["price_source"] = quote.get("source")
        refreshed["price_source_status"] = "verified"
        refreshed["updated_at"] = updated_at
        revenue_month = refreshed.get("revenue_month") or ""
        market_date = refreshed.get("market_date") or ""
        if revenue_month or market_date:
            refreshed["data_version"] = f"revenue {revenue_month or '-'} | quote {market_date or '-'}"
        updated_items.append(refreshed)
        updated_count += 1
    return updated_items, updated_count


def refresh_stock_quotes(items: list[dict], updated_at: str) -> tuple[list[dict], dict]:
    quotes, status = fetch_official_quotes(now_taipei())
    if not status.get("success"):
        return items, status
    refreshed, updated_count = apply_quotes_to_stocks(items, quotes, updated_at)
    status["updated_stock_count"] = updated_count
    status["missing_stock_count"] = max(len(items) - updated_count, 0)
    if updated_count == 0:
        status["success"] = False
        status["error"] = "Official quotes were fetched, but none matched stocks-latest.json."
        return items, status
    return refreshed, status


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
    global QUOTE_REFRESH_STATUS
    source_files = ["stocks-latest.json", "stock-data-meta.json", "stock-master.json"]
    stocks = read_json(DOCS_DATA / "stocks-latest.json", [])
    stock_meta = read_json(DOCS_DATA / "stock-data-meta.json", {})
    items = stocks if isinstance(stocks, list) else as_items(stocks)
    items, QUOTE_REFRESH_STATUS = refresh_stock_quotes(items, updated_at)
    if QUOTE_REFRESH_STATUS.get("success"):
        write_json(DOCS_DATA / "stocks-latest.json", items)
        if isinstance(stock_meta, dict):
            stock_meta = dict(stock_meta)
            stock_meta["updated_at"] = updated_at
            stock_meta["quote_updated_at"] = updated_at
            stock_meta["quote_market_date"] = QUOTE_REFRESH_STATUS.get("market_date")
            stock_meta["quote_source"] = QUOTE_REFRESH_STATUS.get("source")
            stock_meta["quote_count"] = QUOTE_REFRESH_STATUS.get("quote_count")
            write_json(DOCS_DATA / "stock-data-meta.json", stock_meta)
    payload = base_payload(stage, source_files, updated_at, data_version)
    payload.update({
        "date": QUOTE_REFRESH_STATUS.get("market_date") or (stock_meta.get("date") if isinstance(stock_meta, dict) else ""),
        "items": items,
        "universe_count": stock_master_count(),
        "source_count": len([name for name in source_files if (DOCS_DATA / name).exists()]),
        "quote_refresh_status": QUOTE_REFRESH_STATUS,
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
    if QUOTE_REFRESH_STATUS and not QUOTE_REFRESH_STATUS.get("success", False):
        warnings.append("quote_refresh_failed")
        entry["quote_refresh_status"] = QUOTE_REFRESH_STATUS
    elif QUOTE_REFRESH_STATUS:
        entry["quote_refresh_status"] = QUOTE_REFRESH_STATUS
    payload = {
        "updated_at": updated_at,
        "stage": stage,
        "stage_label": STAGES[stage]["label"],
        "timezone": "Asia/Taipei",
        "source_count": len(updated_files),
        "data_version": data_version,
        "warnings": warnings,
        "news_fetch_status": NEWS_FETCH_STATUS,
        "quote_refresh_status": QUOTE_REFRESH_STATUS,
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
    if QUOTE_REFRESH_STATUS.get("success"):
        updated_files.extend([
            "docs/data/stocks-latest.json",
            "docs/data/stock-data-meta.json",
        ])

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
