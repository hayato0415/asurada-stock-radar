from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
SITE_DATA_DIR = BASE_DIR / "docs" / "data"
STOCKS_PATH = SITE_DATA_DIR / "stocks-latest.json"
NEWS_OUTPUT_PATH = SITE_DATA_DIR / "news-events.json"
CONCEPTS_PATH = SITE_DATA_DIR / "concepts-map.json"
CANDIDATES_OUTPUT_PATH = SITE_DATA_DIR / "theme-candidates.json"

MAX_NEWS = 50


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str
    region: str


SOURCES = [
    NewsSource("CMoney 美股新聞快訊", "https://www.cmoney.tw/notes/?tag=76325", "國際"),
    NewsSource("CMoney 台股即時消息", "https://www.cmoney.tw/notes/?navId=twstock_news", "台股"),
    NewsSource("鉅亨網美股新聞", "https://news.cnyes.com/news/cat/wd_stock", "國際"),
    NewsSource("鉅亨網台股新聞", "https://news.cnyes.com/news/cat/tw_stock_news", "台股"),
    NewsSource("MoneyDJ 產業分析新聞", "https://www.moneydj.com/kmdj/common/listnewarticles.aspx?a=X0300000&svc=NW", "台股"),
    NewsSource("MoneyDJ 即時新聞總表", "https://www.moneydj.com/KMDJ/News/NewsRealList.aspx?a=MB010000", "台股"),
]


AI_SERVER_KEYWORDS = [
    "AI伺服器", "AI 伺服器", "NVIDIA", "輝達", "GB200", "GB300", "B200",
    "Blackwell", "Rubin", "H100", "H200", "ASIC", "TPU", "AWS", "Google",
    "Meta", "Microsoft", "CSP", "AI機櫃", "液冷", "散熱", "高功耗",
    "高速傳輸", "800G", "1.6T", "AI資料中心",
]

PCB_KEYWORDS = [
    "PCB", "印刷電路板", "伺服器板", "高階多層板", "HDI", "HLC", "ABF",
    "IC載板", "CCL", "銅箔基板", "玻纖布", "Low Dk", "HVLP", "T-Glass",
    "M9", "Q布", "鑽針", "MSAP", "高頻高速材料", "交換器板",
    "800G交換器", "1.6T交換器",
]

THEME_KEYWORDS: dict[str, list[str]] = {
    "記憶體": ["記憶體", "DRAM", "NAND", "HBM", "SSD", "美光", "Micron", "海力士", "SK hynix", "三星"],
    "AI伺服器": AI_SERVER_KEYWORDS,
    "PCB": PCB_KEYWORDS,
    "CPO / 光通訊 / AI資料中心": ["聯鈞", "3450", "CPO", "光通訊", "矽光子", "800G", "1.6T", "AOC", "COS", "光模組", "雷射封測", "AI資料中心", "源傑科技"],
    "CPO": ["CPO", "光通訊", "矽光子", "光模組", "CoWoS", "800G", "1.6T", "AOC", "COS", "雷射封測", "AI資料中心"],
    "玻璃基板": ["玻璃基板", "TGV", "Glass substrate"],
    "低軌衛星": ["低軌衛星", "衛星", "SpaceX", "Starlink"],
    "重電": ["重電", "電網", "變壓器", "電力設備", "綠電"],
    "被動元件": ["被動元件", "MLCC", "電容", "電阻", "電感"],
    "半導體設備": ["半導體設備", "設備", "先進封裝", "EUV", "CoWoS", "台積電 ADR", "TSMC ADR"],
    "軍工電子": ["軍工", "軍工電子", "國防", "無人機", "航太", "飛彈"],
    "營建資產": ["營建", "資產", "都更", "房市", "建案", "土地"],
    "金融壽險": ["金融", "壽險", "銀行", "Fed", "美債", "利率", "匯率", "美元", "台幣"],
    "原物料": ["油價", "銅價", "黃金", "原物料", "能源"],
}


MANUAL_RELATED_STOCKS: dict[str, list[str]] = {
    "記憶體": ["2337", "2344", "2408", "8299", "3260", "2451", "4967"],
    "AI伺服器": ["2382", "3231", "6669", "2356", "2376", "3022", "2368"],
    "PCB": ["2383", "2368", "3037", "8046", "4958"],
    "AI伺服器 + PCB": ["2382", "3231", "6669", "2356", "2376", "3022", "2383", "2368", "3037", "8046", "4958"],
    "CPO / 光通訊 / AI資料中心": ["3450", "3081", "4979", "3163", "4908", "3363", "6442"],
    "CPO": ["3450", "3081", "4979", "3163", "4908", "3363", "6442"],
    "玻璃基板": ["1802", "1810", "3044"],
    "低軌衛星": ["2313", "6285", "3491", "3596"],
    "重電": ["1504", "1513", "1514", "1605", "1618"],
    "被動元件": ["2327", "2492", "3042", "6173"],
    "半導體設備": ["3131", "3167", "3583", "6187", "7556", "3041"],
    "軍工電子": ["2634", "8033", "8222", "4572"],
    "營建資產": ["2536", "2539", "5534", "5522", "2537", "2543", "1316", "2548"],
    "金融壽險": ["2885", "2889", "2820", "2881", "2882", "2886"],
}


IMPORTANT_KEYWORDS = [
    "美光",
    "Micron",
    "輝達",
    "NVIDIA",
    "AMD",
    "Broadcom",
    "博通",
    "SK 海力士",
    "SK hynix",
    "三星",
    "台積電 ADR",
    "TSMC ADR",
    "SpaceX",
    "Fed",
    "美債",
    "匯率",
    "油價",
    "銅價",
    "漲停",
    "法說",
    "月營收",
    "升評",
    "重大公告",
]


BAD_HOSTS = {"example.com", "www.example.com", "localhost", "127.0.0.1"}


def load_stocks() -> list[dict[str, object]]:
    if not STOCKS_PATH.exists():
        return []
    return json.loads(STOCKS_PATH.read_text(encoding="utf-8"))


def is_real_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc or parsed.netloc.lower() in BAD_HOSTS:
        return False
    if "example.com" in parsed.netloc.lower():
        return False
    return True


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_html(source: NewsSource) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AsuradaRadar/1.0",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    }
    response = requests.get(source.url, headers=headers, timeout=25)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def extract_links(source: NewsSource, html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(source.url, anchor["href"])
        if not title or len(title) < 8 or not is_real_url(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        candidates.append({"title": title, "url": href})
    return candidates


def infer_category(title: str) -> str | None:
    upper_title = title.upper()
    ai_hit = any(keyword.upper() in upper_title for keyword in AI_SERVER_KEYWORDS)
    pcb_hit = any(keyword.upper() in upper_title for keyword in PCB_KEYWORDS)
    if ai_hit and pcb_hit:
        return "AI伺服器 + PCB"
    cpo_hit = any(keyword.upper() in upper_title for keyword in THEME_KEYWORDS["CPO / 光通訊 / AI資料中心"])
    if cpo_hit:
        return "CPO / 光通訊 / AI資料中心"
    for category, keywords in THEME_KEYWORDS.items():
        if any(keyword.upper() in upper_title for keyword in keywords):
            return category
    return None


def infer_impact(title: str) -> str:
    positive = ["強", "漲", "利多", "升評", "成長", "增", "旺", "新高", "看好", "擴產", "需求"]
    negative = ["跌", "利空", "下修", "衰退", "減", "虧", "砍", "疲弱", "風險"]
    if any(word in title for word in negative):
        return "偏空"
    if any(word in title for word in positive):
        return "偏多"
    return "中性"


def infer_strength(title: str) -> str:
    if any(word.upper() in title.upper() for word in IMPORTANT_KEYWORDS):
        return "高"
    if any(word in title for word in ["法說", "月營收", "漲停", "升評", "重大公告"]):
        return "高"
    return "中"


def related_stocks_for(category: str, title: str, stocks: list[dict[str, object]]) -> list[str]:
    related = set(MANUAL_RELATED_STOCKS.get(category, []))
    if "+" in category:
        for part in [item.strip() for item in category.split("+")]:
            related.update(MANUAL_RELATED_STOCKS.get(part, []))
    haystack = title.upper()
    for stock in stocks:
        code = str(stock.get("code", "")).strip()
        name = str(stock.get("name", "")).strip()
        concept = str(stock.get("concept", "")).upper()
        if not code:
            continue
        if name and name.upper() in haystack:
            related.add(code)
        elif category and category.upper() in concept:
            related.add(code)
    return sorted(related)


def related_keywords_for(category: str) -> list[str]:
    if category in THEME_KEYWORDS:
        return THEME_KEYWORDS[category]
    keywords: list[str] = []
    if "+" in category:
        for part in [item.strip() for item in category.split("+")]:
            keywords.extend(THEME_KEYWORDS.get(part, []))
    return list(dict.fromkeys(keywords))


def make_summary(title: str, category: str, source_name: str) -> str:
    return f"{source_name} 消息指出：{title}。此事件被歸類為 {category} 題材，需觀察是否帶動相關族群資金輪動。"


def make_analysis(title: str, category: str, related_stocks: list[str]) -> str:
    stocks_text = "、".join(related_stocks[:8]) if related_stocks else "相關族群"
    return f"阿斯拉連動分析：{category} 題材若延續發酵，可觀察 {stocks_text} 是否同步出現量價轉強、營收確認或法人重新評價。"


TECH_MARKET_KEYWORDS = [
    "AI伺服器", "AI PC", "AI手機", "AI智慧型眼鏡", "智慧眼鏡", "PCB", "CPO", "光通訊", "矽光子",
    "玻璃基板", "記憶體", "半導體", "半導體設備", "低軌衛星", "重電", "被動元件",
    "散熱", "電源", "機器人", "無人機", "軍工電子", "NVIDIA", "輝達", "美光",
    "AMD", "Broadcom", "ASML", "台積電",
]


def infer_market_group(title: str, category: str, keywords: list[str]) -> str:
    text = f"{title} {category} {' '.join(keywords)}".upper()
    if any(word.upper() in text for word in TECH_MARKET_KEYWORDS):
        return "電子股"
    return "非電子類別"


def infer_news_region(region: str) -> str:
    return "國際" if region == "國際" else "台股"


def build_events(limit: int = MAX_NEWS) -> list[dict[str, object]]:
    stocks = load_stocks()
    events: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    for source in SOURCES:
        try:
            html = fetch_html(source)
            links = extract_links(source, html)
        except Exception as exc:
            print(f"[warn] {source.name}: {exc}")
            continue

        for item in links:
            title = item["title"]
            url = item["url"]
            if url in seen_urls or not is_real_url(url):
                continue
            category = infer_category(title)
            if not category:
                continue
            related_stocks = related_stocks_for(category, title, stocks)
            if not related_stocks:
                continue
            keywords = related_keywords_for(category)
            seen_urls.add(url)
            events.append(
                {
                    "date": fetched_at,
                    "title": title,
                    "region": source.region,
                    "category": category,
                    "impact": infer_impact(title),
                    "event_strength": infer_strength(title),
                    "market_group": infer_market_group(title, category, keywords),
                    "news_region": infer_news_region(source.region),
                    "related_keywords": keywords,
                    "related_stocks": related_stocks,
                    "summary": make_summary(title, category, source.name),
                    "asurada_analysis": make_analysis(title, category, related_stocks),
                    "source_name": source.name,
                    "source_url": url,
                    "url": url,
                }
            )
            if len(events) >= limit:
                return events
    return events[:limit]


def write_events(events: list[dict[str, object]], output: Path = NEWS_OUTPUT_PATH) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    legacy_path = BASE_DIR / "docs" / "news-events.json"
    legacy_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def load_concepts() -> dict[str, object]:
    if not CONCEPTS_PATH.exists():
        return {}
    return json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))


def build_theme_candidates(events: list[dict[str, object]]) -> list[dict[str, object]]:
    concepts = load_concepts()
    formal_terms = {str(name).upper() for name in concepts}
    for concept in concepts.values():
        if isinstance(concept, dict):
            for item in concept.get("aliases", []) + concept.get("keywords", []):
                formal_terms.add(str(item).upper())

    now = datetime.now().date()
    recent: list[dict[str, object]] = []
    for event in events:
        raw_date = str(event.get("date", ""))[:10]
        try:
            event_date = datetime.fromisoformat(raw_date).date()
        except ValueError:
            event_date = now
        if event_date >= now - timedelta(days=3):
            recent.append(event)

    keyword_events: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in recent:
        candidates = {str(item).strip() for item in event.get("related_keywords", []) if str(item).strip()}
        if event.get("category"):
            candidates.add(str(event["category"]).strip())
        for keyword in candidates:
            if len(keyword) < 2 or keyword.upper() in formal_terms:
                continue
            keyword_events[keyword].append(event)

    rows: list[dict[str, object]] = []
    for keyword, matched_events in keyword_events.items():
        sources = {str(event.get("source_name", "")) for event in matched_events if event.get("source_name")}
        if len(matched_events) < 3 or len(sources) < 2:
            continue
        related_stocks: list[str] = []
        for event in matched_events:
            related_stocks.extend(str(code) for code in event.get("related_stocks", []))
        rows.append(
            {
                "theme_name": keyword,
                "count": len(matched_events),
                "source_count": len(sources),
                "related_news": matched_events[:5],
                "related_stocks": list(dict.fromkeys(related_stocks))[:12],
                "status": "觀察中",
            }
        )

    rows.sort(key=lambda item: (-int(item["count"]), -int(item["source_count"]), str(item["theme_name"])))
    return rows[:20]


def write_theme_candidates(events: list[dict[str, object]]) -> None:
    CANDIDATES_OUTPUT_PATH.write_text(
        json.dumps(build_theme_candidates(events), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="更新阿斯拉重大新聞雷達資料")
    parser.add_argument("--limit", type=int, default=MAX_NEWS, help="新聞池最多保留幾則，預設 50")
    parser.add_argument("--output", type=Path, default=NEWS_OUTPUT_PATH)
    args = parser.parse_args()
    events = build_events(limit=args.limit)
    write_events(events, args.output)
    write_theme_candidates(events)
    print(json.dumps({"events": len(events), "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
