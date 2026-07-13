#!/usr/bin/env python
"""Build full-market processed data for the static radar site.

Every listed / OTC common stock in the stock master receives one processed
metrics row and one AI ranking row. Missing official data stays null; EPS and
gross margin are never fabricated. Theme rotation is derived from the same full
market universe plus optional manual membership and existing news events.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import tempfile
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import build_stock_master
import update_stock_metrics


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"
MANUAL_DIR = ROOT / "data" / "manual"

STOCK_MASTER = DATA_DIR / "stocks_master.json"
METRICS = DATA_DIR / "stock_metrics_daily.json"
AI_SCORES = DATA_DIR / "ai_scores_daily.json"
THEME_STATS = DATA_DIR / "theme_stats.json"
NEWS_EVENTS = DATA_DIR / "news_events.json"
UPDATE_LOG = DATA_DIR / "update_log.json"
MANUAL_FINANCIALS = MANUAL_DIR / "financial_fundamentals.csv"
MANUAL_THEMES = MANUAL_DIR / "theme_memberships.csv"
TAIPEI = timezone(timedelta(hours=8))
FULL_MARKET_OUTPUTS = (
  STOCK_MASTER,
  METRICS,
  AI_SCORES,
  THEME_STATS,
  UPDATE_LOG,
)


def now_taipei() -> datetime:
  return datetime.now(TAIPEI)


def read_json(path: Path, default: Any) -> Any:
  if not path.exists():
    return default
  return json.loads(path.read_text(encoding="utf-8-sig"))


def write_bytes_atomic(path: Path, content: bytes) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary: Path | None = None
  try:
    with tempfile.NamedTemporaryFile(
      mode="wb",
      dir=path.parent,
      prefix=f".{path.name}.",
      suffix=".tmp",
      delete=False,
    ) as handle:
      temporary = Path(handle.name)
      handle.write(content)
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
    temporary = None
  finally:
    if temporary is not None:
      temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: Any) -> None:
  content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
  write_bytes_atomic(path, content)


def snapshot_files(paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
  return {path: path.read_bytes() if path.exists() else None for path in paths}


def restore_files(snapshot: dict[Path, bytes | None]) -> None:
  for path, content in snapshot.items():
    if content is None:
      path.unlink(missing_ok=True)
    else:
      write_bytes_atomic(path, content)


def number(value: Any) -> float | None:
  if value is None or value == "":
    return None
  try:
    parsed = float(str(value).replace(",", "").replace("%", "").strip())
  except ValueError:
    return None
  if math.isnan(parsed) or math.isinf(parsed):
    return None
  return parsed


def clamp(value: float, min_value: float = 0, max_value: float = 100) -> float:
  return max(min_value, min(max_value, value))


def score_range(value: Any, min_value: float, max_value: float, fallback: float = 38) -> float:
  parsed = number(value)
  if parsed is None or max_value == min_value:
    return fallback
  return clamp(((parsed - min_value) / (max_value - min_value)) * 100)


def normalize_score(value: Any, min_value: float, max_value: float) -> float:
  parsed = number(value)
  if parsed is None or max_value == min_value:
    return 0
  return clamp(((parsed - min_value) / (max_value - min_value)) * 100)


def round_score(value: float) -> float:
  return round(clamp(value), 1)


def round_number(value: Any, digits: int = 2) -> float | None:
  parsed = number(value)
  if parsed is None:
    return None
  return round(parsed, digits)


def load_items(path: Path) -> list[dict[str, Any]]:
  payload = read_json(path, {})
  items = payload.get("items") if isinstance(payload, dict) else payload
  return [item for item in items or [] if isinstance(item, dict)]


def build_map(items: list[dict[str, Any]], key: str = "symbol") -> dict[str, dict[str, Any]]:
  return {str(item.get(key) or ""): item for item in items if item.get(key)}


def is_valid_market(stock: dict[str, Any]) -> bool:
  return stock.get("market") in {"上市", "上櫃"}


def normalize_theme(value: Any) -> str:
  text = str(value or "").strip()
  if not text or text.isdigit():
    return ""
  return text


def source_label(source_type: str) -> str:
  return {
    "manual": "手動題材對應",
    "ai": "AI 題材標籤",
    "news": "新聞事件",
    "master": "主檔產業 / 供應鏈",
  }.get(source_type, source_type)


def unique(values: list[Any]) -> list[Any]:
  seen = set()
  output = []
  for value in values:
    if value in seen or value in (None, ""):
      continue
    seen.add(value)
    output.append(value)
  return output


def load_manual_financials() -> dict[str, dict[str, Any]]:
  if not MANUAL_FINANCIALS.exists():
    MANUAL_FINANCIALS.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_FINANCIALS.write_text(
      "symbol,name,financial_period,eps,gross_margin_pct,source_url\n",
      encoding="utf-8",
    )
    return {}

  manual: dict[str, dict[str, Any]] = {}
  with MANUAL_FINANCIALS.open("r", encoding="utf-8-sig", newline="") as handle:
    for row in csv.DictReader(handle):
      symbol = str(row.get("symbol") or "").strip()
      if not symbol:
        continue
      manual[symbol] = {
        "eps": number(row.get("eps")),
        "gross_margin_pct": number(row.get("gross_margin_pct")),
        "financial_period": (row.get("financial_period") or "").strip() or None,
        "financial_source_url": (row.get("source_url") or "").strip() or None,
      }
  return manual


def load_manual_theme_memberships() -> list[dict[str, Any]]:
  if not MANUAL_THEMES.exists():
    MANUAL_THEMES.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_THEMES.write_text(
      "symbol,name,theme,role,source_url,source_label,updated_at\n",
      encoding="utf-8",
    )
    return []

  with MANUAL_THEMES.open("r", encoding="utf-8-sig", newline="") as handle:
    return [row for row in csv.DictReader(handle) if (row.get("symbol") or "").strip() and (row.get("theme") or "").strip()]


def build_stock_master_with_fallback() -> dict[str, Any]:
  existing = read_json(STOCK_MASTER, {"items": []})
  existing_count = len(existing.get("items", [])) if isinstance(existing, dict) else 0
  try:
    payload = build_stock_master.build_master()
    new_count = len(payload.get("items", [])) if isinstance(payload, dict) else 0
    minimum_count = max(1000, int(existing_count * 0.8))
    if new_count < minimum_count:
      raise ValueError(f"stock master row count {new_count} is below safety threshold {minimum_count}")
    write_json(STOCK_MASTER, payload)
    return payload
  except Exception as exc:  # noqa: BLE001 - preserve last successful master.
    print(f"stocks_master fetch failed; previous file preserved: {exc}")
    raise RuntimeError(f"stock master refresh failed: {exc}") from exc


def build_metrics_with_manual_financials() -> dict[str, Any]:
  payload = update_stock_metrics.build_metrics(Namespace(stock_master=str(STOCK_MASTER), date=""))
  quality = payload.get("quality", {}) if isinstance(payload, dict) else {}
  errors = quality.get("errors") or []
  item_count = len(payload.get("items", [])) if isinstance(payload, dict) else 0
  if errors or item_count < 1000 or not payload.get("date"):
    reason = "; ".join(str(item) for item in errors) or f"invalid metrics payload: rows={item_count}, date={payload.get('date')}"
    raise RuntimeError(f"stock metrics refresh failed; previous file preserved: {reason}")
  manual = load_manual_financials()
  items = payload.get("items", [])

  eps_matched = 0
  gross_matched = 0
  missing_financials: list[str] = []
  for item in items:
    symbol = str(item.get("symbol") or "")
    supplement = manual.get(symbol, {})
    eps = supplement.get("eps")
    gross = supplement.get("gross_margin_pct")
    if eps is not None:
      item["eps"] = round(eps, 2)
      eps_matched += 1
    else:
      item["eps"] = item.get("eps")
    if gross is not None:
      item["gross_margin_pct"] = round(gross, 2)
      gross_matched += 1
    else:
      item["gross_margin_pct"] = item.get("gross_margin_pct")
    item["financial_period"] = supplement.get("financial_period") or item.get("financial_period")
    item["financial_source_url"] = supplement.get("financial_source_url") or item.get("financial_source_url")
    if item.get("eps") is None and item.get("gross_margin_pct") is None:
      missing_financials.append(symbol)

  quality = payload.setdefault("quality", {})
  quality["eps_matched"] = eps_matched
  quality["gross_margin_matched"] = gross_matched
  quality["missing_financials"] = missing_financials
  payload.setdefault("source", {})["financials"] = (
    "data/manual/financial_fundamentals.csv; official financial JSON if integrated"
  )
  write_json(METRICS, payload)
  return payload


def technical_score(metric: dict[str, Any]) -> float:
  return round_score(score_range(metric.get("change_pct"), -8, 8, 42) * 0.65
                     + score_range(metric.get("turnover_rate_pct"), 0, 8, 38) * 0.35)


def chip_score(metric: dict[str, Any]) -> float:
  return round_score(score_range(metric.get("turnover_rate_pct"), 0, 10, 38) * 0.55
                     + score_range(metric.get("volume"), 0, 20_000_000, 35) * 0.45)


def fundamental_score(metric: dict[str, Any]) -> float:
  return round_score(score_range(metric.get("revenue_yoy_pct"), -30, 80, 38) * 0.35
                     + score_range(metric.get("revenue_mom_pct"), -20, 50, 40) * 0.20
                     + score_range(metric.get("eps"), -2, 8, 38) * 0.25
                     + score_range(metric.get("gross_margin_pct"), 0, 50, 38) * 0.20)


def data_quality_score(metric: dict[str, Any]) -> float:
  fields = (
    "trade_price",
    "change_pct",
    "volume",
    "revenue_million",
    "revenue_yoy_pct",
    "eps",
    "gross_margin_pct",
  )
  covered = sum(1 for field in fields if number(metric.get(field)) is not None)
  return round_score((covered / len(fields)) * 100)


def infer_risk(metric: dict[str, Any]) -> str:
  change = number(metric.get("change_pct"))
  turnover = number(metric.get("turnover_rate_pct"))
  volume = number(metric.get("volume"))
  if (change is not None and change >= 7) or (turnover is not None and turnover >= 10):
    return "高"
  if (change is not None and change <= -5) or not volume:
    return "中"
  return "低"


def infer_pattern(metric: dict[str, Any]) -> str:
  if (number(metric.get("revenue_yoy_pct")) or -999) >= 30:
    return "營收高成長"
  if (number(metric.get("gross_margin_pct")) or -999) >= 35:
    return "高毛利率"
  eps = number(metric.get("eps"))
  if eps is not None and eps > 0:
    return "獲利篩選"
  if (number(metric.get("change_pct")) or -999) > 0:
    return "量價轉強"
  return "全市場量化"


def entry_reason(metric: dict[str, Any]) -> str:
  parts: list[str] = []
  if number(metric.get("revenue_yoy_pct")) is not None:
    parts.append(f"營收年增 {metric['revenue_yoy_pct']:.2f}%")
  if number(metric.get("revenue_mom_pct")) is not None:
    parts.append(f"月增 {metric['revenue_mom_pct']:.2f}%")
  if number(metric.get("eps")) is not None:
    parts.append(f"EPS {metric['eps']:.2f}")
  if number(metric.get("gross_margin_pct")) is not None:
    parts.append(f"毛利率 {metric['gross_margin_pct']:.2f}%")
  if number(metric.get("turnover_rate_pct")) is not None:
    parts.append(f"週轉率 {metric['turnover_rate_pct']:.2f}%")
  return "，".join(parts[:4]) if parts else "資料不足，保留於個股查詢檢視。"


def build_ai_scores(stocks_payload: dict[str, Any], metrics_payload: dict[str, Any]) -> dict[str, Any]:
  updated_at = now_taipei().strftime("%Y-%m-%d %H:%M")
  stocks = stocks_payload.get("items", [])
  metric_map = build_map(metrics_payload.get("items", []))
  rows: list[dict[str, Any]] = []

  for stock in stocks:
    symbol = str(stock.get("symbol") or "")
    if not symbol:
      continue
    metric = metric_map.get(symbol, {})
    technical = technical_score(metric)
    chip = chip_score(metric)
    fundamental = fundamental_score(metric)
    quality = data_quality_score(metric)
    news = 35
    total = round_score(technical * 0.22 + chip * 0.18 + fundamental * 0.45 + news * 0.05 + quality * 0.10)
    theme = normalize_theme(stock.get("theme")) or normalize_theme(stock.get("supply_chain")) or normalize_theme(stock.get("industry")) or "未分類"

    rows.append(
      {
        "symbol": symbol,
        "name": stock.get("name"),
        "market": stock.get("market"),
        "industry": stock.get("industry"),
        "theme": theme,
        "pattern": infer_pattern(metric),
        "total_score": total,
        "technical_score": technical,
        "chip_score": chip,
        "fundamental_score": fundamental,
        "news_score": news,
        "data_quality_score": quality,
        "risk_level": infer_risk(metric),
        "entry_reason": entry_reason(metric),
        "market_date": metrics_payload.get("date"),
        "updated_at": updated_at,
      }
    )

  rows.sort(
    key=lambda item: (
      item.get("total_score") or 0,
      item.get("fundamental_score") or 0,
      number(metric_map.get(str(item.get("symbol")), {}).get("revenue_yoy_pct")) or -999999,
    ),
    reverse=True,
  )
  for rank, item in enumerate(rows, start=1):
    item["rank"] = rank

  return {
    "date": metrics_payload.get("date"),
    "updated_at": updated_at,
    "source": {
      "scores": "Derived from stock_metrics_daily.json quantitative fields",
      "news_score": "Neutral placeholder; no external news fetch in this builder",
    },
    "quality": {
      "stock_master_count": len(stocks),
      "items_count": len(rows),
      "data_quality_note": "EPS and gross margin stay null unless supplied by official-compatible data or manual CSV.",
    },
    "items": rows,
  }


def stock_turnover_billion(metric: dict[str, Any]) -> float | None:
  price = number(metric.get("trade_price"))
  volume = number(metric.get("volume"))
  if price is None or volume is None:
    return None
  return round((price * volume) / 100000000, 3)


def theme_reason(source_types: list[str], metric: dict[str, Any]) -> str:
  parts: list[str] = []
  if "news" in source_types:
    parts.append("新聞事件帶動")
  if "ai" in source_types:
    parts.append("AI 題材標籤")
  if "manual" in source_types:
    parts.append("手動題材對應")
  if "master" in source_types:
    parts.append("供應鏈 / 產業歸類")
  if number(metric.get("revenue_yoy_pct")) is not None:
    parts.append(f"營收年增 {metric['revenue_yoy_pct']:.2f}%")
  if number(metric.get("change_pct")) is not None:
    parts.append(f"漲跌 {metric['change_pct']:.2f}%")
  if number(metric.get("turnover_rate_pct")) is not None:
    parts.append(f"週轉率 {metric['turnover_rate_pct']:.2f}%")
  return "；".join(parts[:4]) if parts else "全市場主檔歸類"


def add_theme_member(
  theme_map: dict[str, dict[str, Any]],
  theme: str,
  stock: dict[str, Any],
  metric: dict[str, Any],
  score: dict[str, Any],
  source_type: str,
  news_count: int = 0,
  role: str = "beneficiary",
) -> None:
  clean_theme = normalize_theme(theme)
  if not clean_theme or clean_theme == "未分類":
    return

  symbol = str(stock.get("symbol") or stock.get("code") or score.get("symbol") or "")
  if not symbol or not stock.get("name"):
    return

  theme_item = theme_map.setdefault(
    clean_theme,
    {
      "theme": clean_theme,
      "beneficiary_map": {},
      "high_score_news_count": 0,
      "source_types": set(),
    },
  )
  existing = theme_item["beneficiary_map"].get(symbol)
  if not existing:
    existing = {
      "symbol": symbol,
      "name": stock.get("name"),
      "market": stock.get("market"),
      "industry": stock.get("industry"),
      "theme": clean_theme,
      "trade_price": metric.get("trade_price"),
      "change_pct": metric.get("change_pct"),
      "volume": metric.get("volume"),
      "turnover_rate_pct": metric.get("turnover_rate_pct"),
      "turnover_billion": stock_turnover_billion(metric),
      "revenue_yoy_pct": metric.get("revenue_yoy_pct"),
      "eps": metric.get("eps"),
      "gross_margin_pct": metric.get("gross_margin_pct"),
      "total_score": score.get("total_score"),
      "source_types": [],
      "source_labels": [],
      "roles": [],
      "reason": "",
    }

  existing["source_types"] = unique([*existing.get("source_types", []), source_type])
  existing["source_labels"] = [source_label(value) for value in existing["source_types"]]
  existing["roles"] = unique([*existing.get("roles", []), role])
  existing["reason"] = theme_reason(existing["source_types"], metric)
  theme_item["source_types"].add(source_type)
  theme_item["high_score_news_count"] += news_count
  theme_item["beneficiary_map"][symbol] = existing


def aggregate_theme_map(theme_map: dict[str, dict[str, Any]], updated_at: str, metrics_payload: dict[str, Any], quality_base: dict[str, Any]) -> dict[str, Any]:
  raw_items: list[dict[str, Any]] = []
  for theme_item in theme_map.values():
    beneficiaries = list(theme_item["beneficiary_map"].values())
    if not beneficiaries:
      continue
    change_values = [number(item.get("change_pct")) for item in beneficiaries if number(item.get("change_pct")) is not None]
    score_values = [number(item.get("total_score")) for item in beneficiaries if number(item.get("total_score")) is not None]
    turnover_values = [number(item.get("turnover_billion")) for item in beneficiaries if number(item.get("turnover_billion")) is not None]
    up_count = sum(1 for item in beneficiaries if (number(item.get("change_pct")) or 0) > 0)
    limit_up_count = sum(1 for item in beneficiaries if (number(item.get("change_pct")) or 0) >= 9.5)
    turnover_billion = sum(turnover_values)
    avg_change = sum(change_values) / len(change_values) if change_values else None
    avg_ai_score = sum(score_values) / len(score_values) if score_values else 0

    raw_items.append(
      {
        "theme": theme_item["theme"],
        "theme_change_pct": round_number(avg_change, 2),
        "turnover_billion": round(turnover_billion, 2),
        "up_count": up_count,
        "limit_up_count": limit_up_count,
        "beneficiary_count": len(beneficiaries),
        "high_score_news_count": theme_item["high_score_news_count"],
        "avg_ai_score": round(avg_ai_score, 1),
        "source_types": sorted(theme_item["source_types"]),
        "source_labels": [source_label(value) for value in sorted(theme_item["source_types"])],
        "beneficiary_stocks": sorted(
          beneficiaries,
          key=lambda item: (number(item.get("total_score")) or 0, number(item.get("change_pct")) or -999),
          reverse=True,
        ),
      }
    )

  max_turnover = max([number(item.get("turnover_billion")) or 0 for item in raw_items] + [1])
  max_limit_up = max([number(item.get("limit_up_count")) or 0 for item in raw_items] + [1])
  max_news = max([number(item.get("high_score_news_count")) or 0 for item in raw_items] + [1])

  scored_items: list[dict[str, Any]] = []
  for item in raw_items:
    up_ratio = item["up_count"] / item["beneficiary_count"] if item["beneficiary_count"] else 0
    theme_score = (
      normalize_score(item.get("theme_change_pct"), -5, 10) * 0.25
      + normalize_score(item.get("turnover_billion"), 0, max_turnover) * 0.25
      + up_ratio * 100 * 0.20
      + normalize_score(item.get("limit_up_count"), 0, max_limit_up) * 0.10
      + normalize_score(item.get("avg_ai_score"), 0, 100) * 0.10
      + normalize_score(item.get("high_score_news_count"), 0, max_news) * 0.10
    )
    beneficiaries = item["beneficiary_stocks"]
    leader_stocks = [{"symbol": stock["symbol"], "name": stock["name"]} for stock in beneficiaries[:5]]
    low_base_stocks = [
      {"symbol": stock["symbol"], "name": stock["name"]}
      for stock in beneficiaries
      if (number(stock.get("change_pct")) or 0) < (number(item.get("theme_change_pct")) or 0)
    ][:5]
    scored_items.append(
      {
        **item,
        "theme_score": round(theme_score, 1),
        "leader_stocks": leader_stocks,
        "low_base_stocks": low_base_stocks,
      }
    )

  scored_items.sort(
    key=lambda item: (
      number(item.get("theme_score")) or 0,
      number(item.get("turnover_billion")) or 0,
      number(item.get("theme_change_pct")) or -999,
      number(item.get("beneficiary_count")) or 0,
    ),
    reverse=True,
  )
  for rank, item in enumerate(scored_items, start=1):
    item["rank"] = rank

  return {
    "date": metrics_payload.get("date"),
    "updated_at": updated_at,
    "source": {
      "stock_master": "data/processed/stocks_master.json",
      "stock_metrics": "data/processed/stock_metrics_daily.json",
      "ai_scores": "data/processed/ai_scores_daily.json",
      "news_events": "data/processed/news_events.json",
      "manual_memberships": "data/manual/theme_memberships.csv",
    },
    "quality": quality_base,
    "items": scored_items,
  }


def build_theme_stats(stocks_payload: dict[str, Any], metrics_payload: dict[str, Any], scores_payload: dict[str, Any]) -> dict[str, Any]:
  updated_at = now_taipei().strftime("%Y-%m-%d %H:%M")
  stocks = [stock for stock in stocks_payload.get("items", []) if is_valid_market(stock)]
  metrics = metrics_payload.get("items", [])
  scores = scores_payload.get("items", [])
  news_events = load_items(NEWS_EVENTS)
  manual_memberships = load_manual_theme_memberships()

  stock_map = build_map(stocks)
  metric_map = build_map(metrics)
  score_map = build_map(scores)
  theme_map: dict[str, dict[str, Any]] = {}
  missing_theme: list[str] = []

  for row in manual_memberships:
    symbol = str(row.get("symbol") or "").strip()
    stock = stock_map.get(symbol)
    if not stock:
      continue
    add_theme_member(
      theme_map,
      row.get("theme") or "",
      stock,
      metric_map.get(symbol, {}),
      score_map.get(symbol, {}),
      "manual",
      0,
      row.get("role") or "beneficiary",
    )

  for stock in stocks:
    symbol = str(stock.get("symbol"))
    metric = metric_map.get(symbol, {})
    score = score_map.get(symbol, {})
    score_theme = normalize_theme(score.get("theme"))
    stock_theme = normalize_theme(stock.get("theme"))
    supply_chain = normalize_theme(stock.get("supply_chain"))
    industry = normalize_theme(stock.get("industry"))
    if score_theme:
      add_theme_member(theme_map, score_theme, stock, metric, score, "ai")
    master_theme = stock_theme or supply_chain or industry
    if master_theme:
      add_theme_member(theme_map, master_theme, stock, metric, score, "master")
    else:
      missing_theme.append(symbol)

  for event in news_events:
    event_theme = normalize_theme(event.get("theme") or event.get("category") or event.get("impact_theme"))
    related_stocks = event.get("stocks") or event.get("related_stocks") or []
    high_score = (number(event.get("news_score")) or number(event.get("event_score")) or 0) >= 70
    if not isinstance(related_stocks, list):
      continue
    for news_stock in related_stocks:
      symbol = str(news_stock.get("symbol") or news_stock.get("code") or "")
      stock = stock_map.get(symbol)
      if not stock:
        continue
      add_theme_member(theme_map, event_theme, stock, metric_map.get(symbol, {}), score_map.get(symbol, {}), "news", 1 if high_score else 0)

  metrics_quality = metrics_payload.get("quality", {})
  quality = {
    "stock_master_count": len(stocks),
    "theme_count": len(theme_map),
    "beneficiary_stock_count": sum(len(item["beneficiary_map"]) for item in theme_map.values()),
    "quote_matched": metrics_quality.get("daily_quote_matched", 0),
    "revenue_matched": metrics_quality.get("revenue_matched", 0),
    "eps_matched": metrics_quality.get("eps_matched", 0),
    "gross_margin_matched": metrics_quality.get("gross_margin_matched", 0),
    "news_event_count": len(news_events),
    "manual_membership_count": len(manual_memberships),
    "missing_theme": missing_theme[:100],
    "missing_quote": metrics_quality.get("missing_quote", [])[:100],
    "missing_revenue": metrics_quality.get("missing_revenue", [])[:100],
    "missing_financials": metrics_quality.get("missing_financials", [])[:100],
  }
  payload = aggregate_theme_map(theme_map, updated_at, metrics_payload, quality)
  payload["quality"]["theme_count"] = len(payload.get("items", []))
  write_json(THEME_STATS, payload)
  return payload


def write_update_log(files: list[tuple[str, int, str, str, str]]) -> None:
  updated_at = now_taipei().strftime("%Y-%m-%d %H:%M")
  write_json(
    UPDATE_LOG,
    {
      "updated_at": updated_at,
      "items": [
        {
          "name": file_name,
          "file": file_name,
          "updated_at": updated_at,
          "record_count": count,
          "count": count,
          "status": status,
          "source": source,
          "message": message,
          "error": "" if status in {"ok", "success", "partial"} else message,
        }
        for file_name, count, status, source, message in files
      ],
    },
  )


def main() -> int:
  DATA_DIR.mkdir(parents=True, exist_ok=True)
  snapshot = snapshot_files(FULL_MARKET_OUTPUTS)
  try:
    stocks_payload = build_stock_master_with_fallback()
    metrics_payload = build_metrics_with_manual_financials()
    scores_payload = build_ai_scores(stocks_payload, metrics_payload)
    write_json(AI_SCORES, scores_payload)
    themes_payload = build_theme_stats(stocks_payload, metrics_payload, scores_payload)

    quality = metrics_payload.get("quality", {})
    theme_quality = themes_payload.get("quality", {})
    write_update_log(
      [
        ("stocks_master.json", len(stocks_payload.get("items", [])), "ok", "TWSE ISIN public page", ""),
        ("stock_metrics_daily.json", len(metrics_payload.get("items", [])), "partial" if quality.get("errors") else "ok", "TWSE / TPEx / MOPS", "; ".join(quality.get("errors") or [])),
        ("ai_scores_daily.json", len(scores_payload.get("items", [])), "ok", "Derived quantitative scoring", ""),
        ("theme_stats.json", len(themes_payload.get("items", [])), "partial" if theme_quality.get("missing_theme") else "ok", "Full-market stock, metrics, AI scores, news, manual memberships", "全市場題材輪動已更新"),
        ("update_log.json", 5, "ok", "local builder", ""),
      ]
    )
  except Exception as exc:  # noqa: BLE001 - roll back the complete output set.
    restore_files(snapshot)
    print(f"Full-market refresh failed; all previous outputs restored: {exc}", file=sys.stderr)
    return 1

  print(f"stocks_master: {len(stocks_payload.get('items', []))} rows")
  print(
    "stock_metrics_daily: {count} rows; quote={quote}; revenue={revenue}; eps={eps}; gross_margin={gross}".format(
      count=len(metrics_payload.get("items", [])),
      quote=quality.get("daily_quote_matched", 0),
      revenue=quality.get("revenue_matched", 0),
      eps=quality.get("eps_matched", 0),
      gross=quality.get("gross_margin_matched", 0),
    )
  )
  print(f"ai_scores_daily: {len(scores_payload.get('items', []))} rows")
  print(f"theme_stats: {len(themes_payload.get('items', []))} themes")
  return 0


if __name__ == "__main__":
  sys.exit(main())
