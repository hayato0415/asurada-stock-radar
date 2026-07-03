from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
CONFIG_DIR = ROOT / "data" / "config"
LATEST_DIR = ROOT / "data" / "latest"
SCORECARD_DIR = ROOT / "data" / "scorecards"

VALID_MARKETS = {"上市", "上櫃"}
BAD_THEME_CODES = {"04", "05", "06", "07", "08"}
TAIPEI_TZ = timezone(timedelta(hours=8))

SCORING_WEIGHTS = {
    "version": "2026-07-transparent-v1",
    "updated_at": "",
    "description": "ASURADA AI 選股透明計分權重。新聞與題材只作為資訊標籤，不納入分數。",
    "total_weight": 100,
    "modules": {
        "fundamental": {
            "label": "基本面",
            "weight": 30,
            "description": "依營收年增、營收月增、EPS、毛利率評估。",
        },
        "technical": {
            "label": "技術面",
            "weight": 30,
            "description": "依當日漲跌、近五日/二十日漲跌與價格資料完整度評估。",
        },
        "chip": {
            "label": "籌碼 / 市場交易力道",
            "weight": 25,
            "description": "依成交量、週轉率與五日量能倍率評估市場交易力道。",
        },
        "turnover": {
            "label": "週轉率 / 交易熱度",
            "weight": 15,
            "description": "依週轉率評估交易熱度；缺上市股數時不硬算。",
        },
    },
    "formula": "total_score = fundamental_weighted + technical_weighted + chip_weighted + turnover_weighted",
    "news_scoring": {
        "included": False,
        "weight": 0,
        "note": "新聞通常代表題材已明朗化，因此不納入分數、不參與排名、不作為篩選條件。",
    },
    "theme_scoring": {
        "included": False,
        "weight": 0,
        "note": "題材、產業、概念股只顯示為標籤，不納入分數。",
    },
}


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ).replace(microsecond=0)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def get_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def get_symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("code") or row.get("stock_id") or "").strip()


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "").strip()
        if cleaned in {"", "--", "-", "N/A", "null"}:
            return None
        value = cleaned
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round1(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 1)


def score_range(value: Any, low: float, high: float, max_score: float) -> tuple[float, bool]:
    number = to_float(value)
    if number is None:
        return 0.0, True
    if high == low:
        return max_score, False
    ratio = clamp((number - low) / (high - low), 0.0, 1.0)
    return round(max_score * ratio, 4), False


def rule(
    rule_id: str,
    label: str,
    source_field: str,
    raw_value: Any,
    max_score: float,
    score: float,
    missing: bool,
    description: str,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "label": label,
        "source_field": source_field,
        "raw_value": raw_value,
        "max_score": max_score,
        "score": round1(score) or 0,
        "missing": missing,
        "description": description,
    }


def module_payload(key: str, label: str, weight: float, rules: list[dict[str, Any]]) -> dict[str, Any]:
    score = round(sum(to_float(item.get("score")) or 0 for item in rules), 1)
    missing_count = sum(1 for item in rules if item.get("missing"))
    coverage = round((len(rules) - missing_count) / len(rules) * 100, 1) if rules else 0
    raw_score = round(score / weight * 100, 1) if weight else 0
    return {
        "key": key,
        "label": label,
        "weight": weight,
        "score": score,
        "raw_score": raw_score,
        "coverage_pct": coverage,
        "missing_count": missing_count,
        "rules": rules,
    }


def clean_theme(stock: dict[str, Any], score: dict[str, Any]) -> str:
    candidates = [
        score.get("theme"),
        stock.get("theme"),
        stock.get("supply_chain"),
        stock.get("industry"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text or text in BAD_THEME_CODES:
            continue
        return text
    return "未分類"


def build_modules(metric: dict[str, Any]) -> dict[str, dict[str, Any]]:
    revenue_yoy_score, revenue_yoy_missing = score_range(metric.get("revenue_yoy_pct"), -20, 80, 9)
    revenue_mom_score, revenue_mom_missing = score_range(metric.get("revenue_mom_pct"), -30, 50, 6)
    eps_score, eps_missing = score_range(metric.get("eps"), -2, 8, 8)
    margin_score, margin_missing = score_range(metric.get("gross_margin_pct"), 0, 60, 7)
    fundamental = module_payload(
        "fundamental",
        "基本面",
        30,
        [
            rule("revenue_yoy", "營收年增率", "revenue_yoy_pct", metric.get("revenue_yoy_pct"), 9, revenue_yoy_score, revenue_yoy_missing, "營收年增越高，基本面動能越強。"),
            rule("revenue_mom", "營收月增率", "revenue_mom_pct", metric.get("revenue_mom_pct"), 6, revenue_mom_score, revenue_mom_missing, "營收月增反映近期動能。"),
            rule("eps", "EPS", "eps", metric.get("eps"), 8, eps_score, eps_missing, "EPS 用於確認獲利能力；缺值不補假資料。"),
            rule("gross_margin", "毛利率", "gross_margin_pct", metric.get("gross_margin_pct"), 7, margin_score, margin_missing, "毛利率用於衡量產品與定價品質。"),
        ],
    )

    change_score, change_missing = score_range(metric.get("change_pct"), -8, 10, 12)
    change_5d_score, change_5d_missing = score_range(metric.get("change_5d"), -10, 25, 8)
    change_20d_score, change_20d_missing = score_range(metric.get("change_20d"), -20, 40, 6)
    price_missing = to_float(metric.get("trade_price")) is None
    technical = module_payload(
        "technical",
        "技術面",
        30,
        [
            rule("change_1d", "當日漲跌幅", "change_pct", metric.get("change_pct"), 12, change_score, change_missing, "當日價格強度。"),
            rule("change_5d", "近五日漲跌幅", "change_5d", metric.get("change_5d"), 8, change_5d_score, change_5d_missing, "近五日趨勢延續性。"),
            rule("change_20d", "近二十日漲跌幅", "change_20d", metric.get("change_20d"), 6, change_20d_score, change_20d_missing, "近二十日波段位置。"),
            rule("price_available", "成交價可用", "trade_price", metric.get("trade_price"), 4, 0 if price_missing else 4, price_missing, "有正式成交價才給資料完整分。"),
        ],
    )

    volume_score, volume_missing = score_range(metric.get("volume"), 0, 50_000_000, 10)
    turnover_chip_score, turnover_chip_missing = score_range(metric.get("turnover_rate_pct"), 0, 12, 10)
    volume_ratio_score, volume_ratio_missing = score_range(metric.get("volume_ratio_5d"), 0.5, 4, 5)
    chip = module_payload(
        "chip",
        "籌碼 / 市場交易力道",
        25,
        [
            rule("volume", "成交量", "volume", metric.get("volume"), 10, volume_score, volume_missing, "成交量反映市場參與度。"),
            rule("turnover_chip", "週轉率交易力道", "turnover_rate_pct", metric.get("turnover_rate_pct"), 10, turnover_chip_score, turnover_chip_missing, "週轉率反映籌碼換手。"),
            rule("volume_ratio_5d", "五日量能倍率", "volume_ratio_5d", metric.get("volume_ratio_5d"), 5, volume_ratio_score, volume_ratio_missing, "量能倍率反映資金是否放大。"),
        ],
    )

    turnover_score, turnover_missing = score_range(metric.get("turnover_rate_pct"), 0, 12, 15)
    turnover = module_payload(
        "turnover",
        "週轉率 / 交易熱度",
        15,
        [
            rule("turnover_rate", "週轉率", "turnover_rate_pct", metric.get("turnover_rate_pct"), 15, turnover_score, turnover_missing, "週轉率越高，交易熱度越高；無上市股數時不硬算。"),
        ],
    )

    return {
        "fundamental": fundamental,
        "technical": technical,
        "chip": chip,
        "turnover": turnover,
    }


def infer_risk(metric: dict[str, Any]) -> str:
    turnover = to_float(metric.get("turnover_rate_pct"))
    change = to_float(metric.get("change_pct"))
    volume = to_float(metric.get("volume"))
    if turnover is not None and turnover >= 10:
        return "高"
    if change is not None and change >= 7:
        return "高"
    if volume is not None and volume < 100_000:
        return "低流動"
    if turnover is not None and turnover < 0.2:
        return "低"
    return "中"


def infer_entry_reason(metric: dict[str, Any]) -> str:
    parts: list[str] = []
    revenue_yoy = to_float(metric.get("revenue_yoy_pct"))
    revenue_mom = to_float(metric.get("revenue_mom_pct"))
    eps = to_float(metric.get("eps"))
    margin = to_float(metric.get("gross_margin_pct"))
    turnover = to_float(metric.get("turnover_rate_pct"))
    if revenue_yoy is not None:
        parts.append(f"營收年增 {revenue_yoy:.1f}%")
    if revenue_mom is not None:
        parts.append(f"月增 {revenue_mom:.1f}%")
    if eps is not None:
        parts.append(f"EPS {eps:.2f}")
    if margin is not None:
        parts.append(f"毛利率 {margin:.1f}%")
    if turnover is not None:
        parts.append(f"週轉率 {turnover:.2f}%")
    if not parts:
        return "資料不足，保留於個股查詢檢視。"
    return "，".join(parts[:4])


def main() -> None:
    build_time = now_taipei()
    build_id = build_time.strftime("%Y%m%d-%H%M-scorecards")

    stocks_payload = read_json(PROCESSED_DIR / "stocks_master.json", {})
    metrics_payload = read_json(PROCESSED_DIR / "stock_metrics_daily.json", {})
    scores_payload = read_json(PROCESSED_DIR / "ai_scores_daily.json", {})

    stocks = [row for row in get_items(stocks_payload) if str(row.get("market") or "").strip() in VALID_MARKETS]
    metrics_by_symbol = {get_symbol(row): row for row in get_items(metrics_payload) if get_symbol(row)}
    old_scores_by_symbol = {get_symbol(row): row for row in get_items(scores_payload) if get_symbol(row)}

    updated_at = build_time.isoformat()
    content_latest_at = (
        metrics_payload.get("date")
        or metrics_payload.get("content_latest_at")
        or metrics_payload.get("updated_at")
        or updated_at
        if isinstance(metrics_payload, dict)
        else updated_at
    )
    revenue_month = metrics_payload.get("revenue_month") if isinstance(metrics_payload, dict) else None

    config = dict(SCORING_WEIGHTS)
    config["updated_at"] = updated_at
    write_json(CONFIG_DIR / "scoring-weights.json", config)

    summaries: list[dict[str, Any]] = []
    for stock in stocks:
        symbol = get_symbol(stock)
        if not symbol:
            continue
        metric = dict(metrics_by_symbol.get(symbol, {}))
        previous_score = old_scores_by_symbol.get(symbol, {})
        name = stock.get("name") or metric.get("name") or previous_score.get("name") or symbol
        theme = clean_theme(stock, previous_score)
        modules = build_modules(metric)
        total_score = round(sum(module["score"] for module in modules.values()), 1)
        weighted_scores = {key: module["score"] for key, module in modules.items()}
        coverage_values = [module["coverage_pct"] for module in modules.values()]
        data_quality_score = round(sum(coverage_values) / len(coverage_values), 1) if coverage_values else 0
        missing_fields = [
            item["source_field"]
            for module in modules.values()
            for item in module["rules"]
            if item.get("missing")
        ]

        summary = {
            "symbol": symbol,
            "code": symbol,
            "name": name,
            "market": stock.get("market"),
            "industry": stock.get("industry") or "--",
            "theme": theme,
            "supply_chain": stock.get("supply_chain") or stock.get("industry") or "--",
            "trade_price": metric.get("trade_price"),
            "change_pct": metric.get("change_pct"),
            "volume": metric.get("volume"),
            "turnover_rate_pct": metric.get("turnover_rate_pct"),
            "revenue_million": metric.get("revenue_million"),
            "revenue_mom_pct": metric.get("revenue_mom_pct"),
            "revenue_yoy_pct": metric.get("revenue_yoy_pct"),
            "eps": metric.get("eps"),
            "gross_margin_pct": metric.get("gross_margin_pct"),
            "financial_period": metric.get("financial_period") or revenue_month,
            "fundamental_score": modules["fundamental"]["raw_score"],
            "technical_score": modules["technical"]["raw_score"],
            "chip_score": modules["chip"]["raw_score"],
            "turnover_score": modules["turnover"]["raw_score"],
            "weighted_scores": weighted_scores,
            "total_score": total_score,
            "risk_level": previous_score.get("risk_level") or infer_risk(metric),
            "entry_reason": previous_score.get("entry_reason") or infer_entry_reason(metric),
            "data_quality_score": data_quality_score,
            "updated_at": updated_at,
            "content_latest_at": content_latest_at,
            "scorecard_path": f"data/scorecards/{symbol}.json",
            "news_scoring_included": False,
            "theme_scoring_included": False,
        }

        scorecard = {
            "build_id": build_id,
            "updated_at": updated_at,
            "content_latest_at": content_latest_at,
            "symbol": symbol,
            "name": name,
            "market": summary["market"],
            "industry": summary["industry"],
            "theme": theme,
            "formula": config["formula"],
            "weights": config["modules"],
            "news_scoring": config["news_scoring"],
            "theme_scoring": config["theme_scoring"],
            "modules": modules,
            "total_score": total_score,
            "summary": summary,
            "missing_fields": sorted(set(missing_fields)),
            "data_sources": {
                "stock_master": "data/processed/stocks_master.json",
                "metrics": "data/processed/stock_metrics_daily.json",
                "manual_financials": "data/manual/financial_fundamentals.csv if available",
            },
        }
        write_json(SCORECARD_DIR / f"{symbol}.json", scorecard)
        summaries.append(summary)

    summaries.sort(
        key=lambda item: (
            -(to_float(item.get("total_score")) or -1),
            -(to_float(item.get("fundamental_score")) or -1),
            -(to_float(item.get("revenue_yoy_pct")) or -9999),
            str(item.get("symbol") or ""),
        )
    )
    for index, item in enumerate(summaries, start=1):
        item["rank"] = index
        item["build_id"] = build_id

    top100 = summaries[:100]
    latest_payload = {
        "build_id": build_id,
        "updated_at": updated_at,
        "content_latest_at": content_latest_at,
        "formula": config["formula"],
        "weights": config["modules"],
        "news_scoring": config["news_scoring"],
        "theme_scoring": config["theme_scoring"],
        "items_count": len(top100),
        "universe_count": len(summaries),
        "items": top100,
    }
    write_json(LATEST_DIR / "ai-ranking-top100.json", latest_payload)

    meta_payload = {
        "build_id": build_id,
        "updated_at": updated_at,
        "content_latest_at": content_latest_at,
        "universe_count": len(summaries),
        "top100_count": len(top100),
        "formula": config["formula"],
        "weights": config["modules"],
        "news_scoring": config["news_scoring"],
        "theme_scoring": config["theme_scoring"],
        "data_sources": latest_payload.get("data_sources", {}),
        "quality": {
            "scorecards_written": len(summaries),
            "stock_master_count": len(stocks),
            "metrics_count": len(metrics_by_symbol),
            "missing_metric_count": sum(1 for item in summaries if item.get("data_quality_score") == 0),
        },
    }
    write_json(LATEST_DIR / "scoring-meta.json", meta_payload)

    processed_scores = {
        "build_id": build_id,
        "updated_at": updated_at,
        "content_latest_at": content_latest_at,
        "source": "scripts/build_ai_scorecards.py",
        "formula": config["formula"],
        "items_count": len(summaries),
        "items": summaries,
    }
    write_json(PROCESSED_DIR / "ai_scores_daily.json", processed_scores)

    print(f"AI scorecards built: {len(summaries)} stocks, top100={len(top100)}, build_id={build_id}")


if __name__ == "__main__":
    main()
