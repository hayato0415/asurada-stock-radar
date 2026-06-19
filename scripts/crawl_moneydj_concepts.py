#!/usr/bin/env python3

import csv
import html
import json
import re
import ssl
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


SOURCE = "MoneyDJ"
LIST_URL = "https://www.moneydj.com/z/zg/zge/zge_E_E.djhtm"
OUTPUT_DIR = Path("data")
CATEGORY_CSV = OUTPUT_DIR / "moneydj_concept_categories.csv"
STOCK_CSV = OUTPUT_DIR / "moneydj_concept_stocks.csv"
REPORT_JSON = OUTPUT_DIR / "moneydj_crawl_report.json"
UPDATED_AT = date.today().isoformat()

FIRST_CONCEPT_CODE = "EH001276"
REQUIRED_STOCKS = {
    "3131": "\u5f18\u5851",
    "3037": "\u6b23\u8208",
}


def fetch_bytes(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AsuradaMoneyDJCrawler/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except ssl.SSLCertVerificationError:
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=30, context=context) as response:
            return response.read()
    except URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            context = ssl._create_unverified_context()
            with urlopen(request, timeout=30, context=context) as response:
                return response.read()
        raise


def decode_html(raw_bytes):
    best_text = ""
    best_score = -10**9
    for encoding in ("cp950", "big5", "utf-8"):
        text = raw_bytes.decode(encoding, errors="replace")
        score = (
            text.count("\u6982\u5ff5\u80a1") * 20
            + text.count("MarketChange") * 5
            + text.count("GenLink2stk") * 5
            + len(re.findall(r"<select[^>]*name=[\"']M1[\"']", text, flags=re.I)) * 15
            - text.count("\ufffd") * 20
        )
        if score > best_score:
            best_text = text
            best_score = score
    return best_text


def fetch_html(url):
    return decode_html(fetch_bytes(url))


def clean_text(value):
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def extract_concept_code(value):
    value = html.unescape(value or "").strip()
    code = re.search(r"\b([A-Z]{1,4}\d{3,})\b", value, flags=re.I)
    if code:
        return code.group(1).upper()
    page_code = re.search(r"zge_([A-Za-z0-9]+)_(?:E|1|10)\.djhtm", value, flags=re.I)
    return page_code.group(1).upper() if page_code else ""


def parse_categories(page_html):
    select_match = re.search(
        r"<select[^>]*name=[\"']M1[\"'][^>]*>(.*?)</select>",
        page_html,
        flags=re.I | re.S,
    )
    if not select_match:
        return []

    rows = []
    seen = set()
    option_pattern = re.compile(r'<option value="([^"]+)"[^>]*>(.*?)</option>', flags=re.I | re.S)
    for match in option_pattern.finditer(select_match.group(1)):
        concept_code = extract_concept_code(match.group(1))
        concept_name = clean_text(match.group(2))
        if not concept_code or not concept_name or concept_code in seen:
            continue
        seen.add(concept_code)
        rows.append(
            {
                "display_order": len(rows) + 1,
                "concept_code": concept_code,
                "concept_name": concept_name,
                "source": SOURCE,
                "updated_at": UPDATED_AT,
                "status": "active",
            }
        )
    return rows


def parse_market_change_urls(page_html):
    url_map = {}
    for call in re.finditer(r"MarketChange\s*\((.*?)\)", page_html, flags=re.I | re.S):
        args = re.findall(r"['\"]([^'\"]+)['\"]", call.group(1))
        concept_code = next((extract_concept_code(arg) for arg in args if extract_concept_code(arg)), "")
        source_url = next((urljoin(LIST_URL, arg) for arg in args if "zge_" in arg.lower()), "")
        if concept_code and source_url:
            url_map[concept_code] = source_url
    return url_map


def concept_url_candidates(concept_code, url_map):
    if concept_code in url_map:
        return [url_map[concept_code]]
    return [
        f"https://www.moneydj.com/z/zg/zge/zge_{concept_code}_E.djhtm",
        f"https://www.moneydj.com/z/zg/zge/zge_{concept_code}_1.djhtm",
        f"https://www.moneydj.com/z/zg/zge/zge_{concept_code}_10.djhtm",
    ]


def parse_stocks(concept_html):
    pattern = re.compile(r"GenLink2stk\(['\"]AS(\d{4})['\"],['\"]([^'%\"]+)['\"]\)")
    rows = []
    seen = set()
    for match in pattern.finditer(concept_html):
        stock_id = match.group(1)
        stock_name = clean_text(match.group(2))
        if not stock_id or not stock_name or stock_id in seen:
            continue
        seen.add(stock_id)
        rows.append({"stock_id": stock_id, "stock_name": stock_name})
    return rows


def fetch_first_concept_stocks(first_category, url_map):
    errors = []
    for source_url in concept_url_candidates(first_category["concept_code"], url_map):
        try:
            concept_html = fetch_html(source_url)
            stocks = parse_stocks(concept_html)
            if stocks:
                return source_url, stocks, errors
            errors.append(f"{source_url}: 0 stocks")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{source_url}: {exc}")
    return "", [], errors


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(report):
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parse_errors = []

    try:
        page_html = fetch_html(LIST_URL)
        categories = parse_categories(page_html)
        if not categories:
            raise RuntimeError('No options found from select[name="M1"].')

        first_category = categories[0]
        if first_category["concept_code"] != FIRST_CONCEPT_CODE:
            parse_errors.append(f"first concept is {first_category['concept_code']}, expected {FIRST_CONCEPT_CODE}")

        url_map = parse_market_change_urls(page_html)
        source_url, first_stocks, fetch_errors = fetch_first_concept_stocks(first_category, url_map)
        parse_errors.extend(fetch_errors if not first_stocks else [])

        stock_rows = []
        for index, stock in enumerate(first_stocks, start=1):
            stock_rows.append(
                {
                    "display_order": first_category["display_order"],
                    "concept_code": first_category["concept_code"],
                    "concept_name": first_category["concept_name"],
                    "stock_order": index,
                    "stock_id": stock["stock_id"],
                    "stock_name": stock["stock_name"],
                    "source": SOURCE,
                    "source_url": source_url,
                    "updated_at": UPDATED_AT,
                    "status": "active",
                }
            )

        first_stock_map = {row["stock_id"]: row["stock_name"] for row in stock_rows}
        for stock_id, stock_name in REQUIRED_STOCKS.items():
            if first_stock_map.get(stock_id) != stock_name:
                parse_errors.append(f"first concept missing {stock_id} {stock_name}")

        report = {
            "categories_total": len(categories),
            "first_concept_code": first_category["concept_code"],
            "first_concept_name": first_category["concept_name"],
            "first_concept_stocks_total": len(stock_rows),
            "stocks_total": len(stock_rows),
            "unique_stocks_total": len({row["stock_id"] for row in stock_rows}),
            "parse_errors": parse_errors,
            "updated_at": UPDATED_AT,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

        if parse_errors:
            write_report(report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        write_csv(
            CATEGORY_CSV,
            categories,
            ["display_order", "concept_code", "concept_name", "source", "updated_at", "status"],
        )
        write_csv(
            STOCK_CSV,
            stock_rows,
            [
                "display_order",
                "concept_code",
                "concept_name",
                "stock_order",
                "stock_id",
                "stock_name",
                "source",
                "source_url",
                "updated_at",
                "status",
            ],
        )
        write_report(report)

        print(f"categories: {len(categories)}")
        print(f"first_concept_code: {first_category['concept_code']}")
        print(f"first_concept_name: {first_category['concept_name']}")
        print(f"first_concept_stocks: {len(stock_rows)}")
        print(f"has_3131_hongsu: {'yes' if first_stock_map.get('3131') == REQUIRED_STOCKS['3131'] else 'no'}")
        print(f"has_3037_xinxing: {'yes' if first_stock_map.get('3037') == REQUIRED_STOCKS['3037'] else 'no'}")
        print(f"has_AI_smart_glasses: {'yes' if any('AI智慧眼鏡' in row['concept_name'] for row in categories) else 'no'}")
        print(f"has_CoWoS: {'yes' if any('CoWoS' in row['concept_name'] for row in categories) else 'no'}")
        print(f"has_Google_TPU: {'yes' if any('Google TPU' in row['concept_name'] for row in categories) else 'no'}")
        print(f"has_HDI_board: {'yes' if any('HDI板' in row['concept_name'] for row in categories) else 'no'}")
        print(f"has_IC_substrate: {'yes' if any('IC基板' in row['concept_name'] for row in categories) else 'no'}")
        return 0
    except Exception as exc:
        report = {
            "categories_total": 0,
            "stocks_total": 0,
            "unique_stocks_total": 0,
            "parse_errors": [str(exc)],
            "updated_at": UPDATED_AT,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_report(report)
        print(f"crawl failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
