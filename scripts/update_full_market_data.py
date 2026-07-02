#!/usr/bin/env python
"""Build full-market processed data for the static radar site.

This script keeps the front-end honest: every listed / OTC common stock in the
stock master receives one processed metrics row and one AI ranking row. Missing
official data stays null; EPS and gross margin are never fabricated.
"""

from __future__ import annotations

import csv
import json
import math
import sys
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
UPDATE_LOG = DATA_DIR / "update_log.json"
MANUAL_FINANCIALS = MANUAL_DIR / "financial_fundamentals.csv"
TAIPEI = timezone(timedelta(hours=8))


def now_taipei() -> datetime:
  return datetime.now(TAIPEI)


def read_json(path: Path, default: Any) -> Any:
  if not path.exists():
    return default
  return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def round_score(value: float) -> float:
  return round(clamp(value), 1)


def load_items(path: Path) -> list[dict[str, Any]]:
  payload = read_json(path, {})
  items = payload.get("items") if isinstance(payload, dict) else payload
  return [item for item in items or [] if isinstance(item, dict)]


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


def build_stock_master_with_fallback() -> dict[str, Any]:
  try:
    payload = build_stock_master.build_master()
    write_json(STOCK_MASTER, payload)
    return payload
  except Exception as exc:  # noqa: BLE001 - preserve last successful master.
    print(f"stocks_master fetch failed, using existing file: {exc}")
    payload = read_json(STOCK_MASTER, {"items": []})
    payload.setdefault("warnings", []).append(f"TWSE ISIN fetch failed: {exc}")
    return payload


def build_metrics_with_manual_financials() -> dict[str, Any]:
  payload = update_stock_metrics.build_metrics(Namespace(stock_master=str(STOCK_MASTER), date=""))
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
  metric_map = {str(item.get("symbol")): item for item in metrics_payload.get("items", [])}
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
    theme = stock.get("theme") or stock.get("supply_chain") or stock.get("industry") or "未分類"

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


def write_update_log(files: list[tuple[str, int, str, str]]) -> None:
  updated_at = now_taipei().strftime("%Y-%m-%d %H:%M")
  write_json(
    UPDATE_LOG,
    {
      "updated_at": updated_at,
      "items": [
        {"file": file_name, "updated_at": updated_at, "count": count, "status": status, "error": error}
        for file_name, count, status, error in files
      ],
    },
  )


def main() -> int:
  DATA_DIR.mkdir(parents=True, exist_ok=True)
  stocks_payload = build_stock_master_with_fallback()
  metrics_payload = build_metrics_with_manual_financials()
  scores_payload = build_ai_scores(stocks_payload, metrics_payload)
  write_json(AI_SCORES, scores_payload)

  quality = metrics_payload.get("quality", {})
  write_update_log(
    [
      ("stocks_master.json", len(stocks_payload.get("items", [])), "ok", ""),
      ("stock_metrics_daily.json", len(metrics_payload.get("items", [])), "ok", "; ".join(quality.get("errors") or [])),
      ("ai_scores_daily.json", len(scores_payload.get("items", [])), "ok", ""),
      ("update_log.json", 4, "ok", ""),
    ]
  )

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
  return 0


if __name__ == "__main__":
  sys.exit(main())
