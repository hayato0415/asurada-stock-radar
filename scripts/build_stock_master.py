#!/usr/bin/env python
"""Build listed / OTC Taiwan stock master data for the static site.

The front-end must not scrape external pages, so this script is the planned
data-build entrypoint. It reads TWSE ISIN public pages and writes a compact
stock master JSON under data/processed/.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "processed" / "stocks_master.json"
TAIPEI = timezone(timedelta(hours=8))

SOURCES = [
    ("上市", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"),
    ("上櫃", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"),
]


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "ASURADA-Stock-Radar/1.0"})
    context = ssl._create_unverified_context()
    with urlopen(request, timeout=30, context=context) as response:
        raw = response.read()
    for encoding in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return unescape(text).strip()


def parse_isin_table(html: str, market: str) -> list[dict]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.I | re.S)
    stocks: list[dict] = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if len(cells) < 6:
            continue
        first = strip_tags(cells[0])
        match = re.match(r"^(\d{4,6})\s+(.+)$", first)
        if not match:
            continue

        code, name = match.groups()
        industry = strip_tags(cells[4])
        cfi_code = strip_tags(cells[5])
        if not industry or not cfi_code.startswith("ES"):
            continue

        stocks.append(
            {
                "symbol": code,
                "name": name,
                "market": market,
                "industry": industry,
                "theme": "",
                "supply_chain": industry,
                "data_source": "TWSE ISIN public page",
            }
        )
    return stocks


def build_master() -> dict:
    items: list[dict] = []
    for market, url in SOURCES:
        html = fetch_text(url)
        parsed = parse_isin_table(html, market)
        print(f"{market}: {len(parsed)} stocks")
        items.extend(parsed)

    unique = {item["symbol"]: item for item in items}
    now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
    return {
        "updated_at": now,
        "source": "TWSE ISIN public pages",
        "items": sorted(unique.values(), key=lambda item: item["symbol"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    payload = build_master()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['items'])} stocks to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
