#!/usr/bin/env python
"""Validate unified ASURADA site data before committing/deploying."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
DOCS_PROCESSED = DOCS_DATA / "processed"

SITE_META = DOCS_DATA / "site_meta.json"
DATA_STATUS = DOCS_DATA / "data_status.json"
RADAR_JSON = DOCS_DATA / "radar.json"
STOCK_METRICS = DOCS_PROCESSED / "stock_metrics_daily.json"
STOCK_MASTER = DOCS_PROCESSED / "stocks_master.json"
FACTOR_STATUS = DOCS_PROCESSED / "factor-scores.status.json"
FACTOR_SCORES = DOCS_PROCESSED / "factor-scores.json"
NEWS_EVENTS = DOCS_PROCESSED / "news_events.json"
MIN_QUOTE_COVERAGE_RATIO = 0.80


def read_json(path: Path) -> Any:
  with path.open("r", encoding="utf-8-sig") as handle:
    return json.load(handle)


def get_items(payload: Any) -> list[Any]:
  if isinstance(payload, list):
    return payload
  if not isinstance(payload, dict):
    return []
  for key in ("items", "data", "scores", "stocks", "rows", "rankings", "events", "files"):
    value = payload.get(key)
    if isinstance(value, list):
      return value
  return []


def market_key(value: Any) -> str:
  text = str(value or "").strip().lower()
  if text in {"上市", "twse", "listed"} or "上市" in text:
    return "twse"
  if text in {"上櫃", "tpex", "otc"} or "上櫃" in text:
    return "tpex"
  return ""


def symbol_key(item: dict[str, Any]) -> str:
  return str(item.get("symbol") or item.get("code") or "").strip()


def minimum_quote_count(expected: int) -> int:
  return max(1, math.ceil(expected * MIN_QUOTE_COVERAGE_RATIO))


def normalize_date(value: Any) -> str:
  if value in (None, ""):
    return ""
  text = str(value).strip()
  if "T" in text:
    text = text.split("T", 1)[0]
  if " " in text:
    text = text.split(" ", 1)[0]
  return text[:10]


def first_existing(payload: Any, keys: tuple[str, ...]) -> Any:
  if not isinstance(payload, dict):
    return None
  for key in keys:
    value = payload.get(key)
    if value not in (None, ""):
      return value
  return None


def payload_date(payload: Any) -> str:
  value = first_existing(payload, (
    "latest_trade_date",
    "trade_date",
    "content_latest_at",
    "market_date",
    "date",
    "data_date",
  ))
  if value:
    return normalize_date(value)
  items = get_items(payload)
  if items and isinstance(items[0], dict):
    return normalize_date(first_existing(
      items[0],
      ("latest_trade_date", "trade_date", "market_date", "date", "dataDate", "data_date"),
    ))
  return ""


def ensure_exists(path: Path, errors: list[str]) -> bool:
  if path.exists():
    return True
  errors.append(f"missing file: {path.relative_to(ROOT)}")
  return False


def require_same_date(label: str, payload: Any, expected: str, errors: list[str]) -> None:
  actual = payload_date(payload)
  if actual != expected:
    errors.append(f"{label} latest_trade_date mismatch: {actual or '--'} != {expected or '--'}")


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--strict", action="store_true", help="Exit non-zero when validation errors are found.")
  args = parser.parse_args()

  errors: list[str] = []
  warnings: list[str] = []

  required = [
    SITE_META,
    DATA_STATUS,
    RADAR_JSON,
    STOCK_MASTER,
    STOCK_METRICS,
    FACTOR_STATUS,
    FACTOR_SCORES,
    NEWS_EVENTS,
  ]
  if not all(ensure_exists(path, errors) for path in required):
    for error in errors:
      print(f"ERROR: {error}")
    return 1 if args.strict else 0

  site_meta = read_json(SITE_META)
  data_status = read_json(DATA_STATUS)
  radar = read_json(RADAR_JSON)
  stock_master = read_json(STOCK_MASTER)
  stock_metrics = read_json(STOCK_METRICS)
  factor_status = read_json(FACTOR_STATUS)
  factor_scores = read_json(FACTOR_SCORES)
  news_events = read_json(NEWS_EVENTS)

  expected = normalize_date(site_meta.get("latest_trade_date"))
  if not expected:
    errors.append("site_meta.json does not contain latest_trade_date")

  require_same_date("radar.json", radar, expected, errors)
  require_same_date("stock_metrics_daily.json", stock_metrics, expected, errors)
  require_same_date("factor-scores.status.json", factor_status, expected, errors)
  require_same_date("factor-scores.json", factor_scores, expected, errors)

  stock_items = get_items(stock_metrics)
  if not any(str(item.get("symbol") or item.get("code")) == "2337" for item in stock_items if isinstance(item, dict)):
    errors.append("stock_metrics_daily.json does not contain symbol 2337, so stock.html?symbol=2337 cannot be verified")

  master_items = [item for item in get_items(stock_master) if isinstance(item, dict)]
  master_markets = {symbol_key(item): market_key(item.get("market")) for item in master_items if symbol_key(item)}
  expected_by_market = {
    market: sum(1 for value in master_markets.values() if value == market)
    for market in ("twse", "tpex")
  }
  metric_quote_symbols = {
    market: {
      symbol_key(item)
      for item in stock_items
      if isinstance(item, dict)
      and master_markets.get(symbol_key(item)) == market
      and any(item.get(key) is not None for key in ("trade_price", "change_pct", "volume"))
    }
    for market in ("twse", "tpex")
  }
  radar_symbols = {
    market: {
      symbol_key(item)
      for item in get_items(radar)
      if isinstance(item, dict) and market_key(item.get("market")) == market and symbol_key(item)
    }
    for market in ("twse", "tpex")
  }
  for market in ("twse", "tpex"):
    required_count = minimum_quote_count(expected_by_market[market])
    if len(metric_quote_symbols[market]) < required_count:
      errors.append(
        f"stock_metrics_daily.json {market.upper()} quote coverage "
        f"{len(metric_quote_symbols[market])} < {required_count} ({MIN_QUOTE_COVERAGE_RATIO:.0%})"
      )
    if len(radar_symbols[market]) < required_count:
      errors.append(
        f"radar.json {market.upper()} quote coverage "
        f"{len(radar_symbols[market])} < {required_count} ({MIN_QUOTE_COVERAGE_RATIO:.0%})"
      )

  radar_source_dates = radar.get("source_dates", {}) if isinstance(radar, dict) else {}
  if not isinstance(radar_source_dates, dict):
    radar_source_dates = {}
  if set(radar_source_dates) != {"twse", "tpex"} or set(radar_source_dates.values()) != {expected}:
    errors.append(f"radar.json TWSE/TPEx source dates are not synchronized to {expected}: {radar_source_dates}")

  metrics_quality = stock_metrics.get("quality", {}) if isinstance(stock_metrics, dict) else {}
  metric_source_dates = metrics_quality.get("daily_quote_source_dates", {}) if isinstance(metrics_quality, dict) else {}
  if not isinstance(metric_source_dates, dict):
    metric_source_dates = {}
  if set(metric_source_dates) != {"twse", "tpex"} or set(metric_source_dates.values()) != {expected}:
    errors.append(
      f"stock_metrics_daily.json TWSE/TPEx source dates are not synchronized to {expected}: {metric_source_dates}"
    )

  if isinstance(factor_status, dict):
    if factor_status.get("ok") is False:
      errors.append(f"factor-scores.status.json ok=false: {factor_status.get('failed_reasons') or factor_status.get('message') or 'unknown reason'}")
    if factor_status.get("previous_data_preserved"):
      errors.append("factor-scores.status.json preserved previous data after a failed refresh")
    for market, key in (("twse", "twse_quote_matched"), ("tpex", "tpex_quote_matched")):
      actual = int(factor_status.get(key) or 0)
      required_count = minimum_quote_count(expected_by_market[market])
      if actual < required_count:
        errors.append(
          f"factor-scores.status.json {market.upper()} quote coverage "
          f"{actual} < {required_count} ({MIN_QUOTE_COVERAGE_RATIO:.0%})"
        )
    factor_source_status = factor_status.get("source_status", [])
    if not isinstance(factor_source_status, list):
      factor_source_status = []
    factor_quote_dates = {
      str(item.get("source_date") or "")
      for item in factor_source_status[:2]
      if isinstance(item, dict) and item.get("source_date")
    }
    if factor_quote_dates != {expected}:
      errors.append(
        f"factor-scores.status.json TWSE/TPEx quote dates are not synchronized to {expected}: "
        f"{sorted(factor_quote_dates)}"
      )

  news_items = get_items(news_events)
  if not isinstance(news_events, dict) or news_events.get("source_pipeline") != "update_news_events":
    errors.append("news_events.json is not generated from the official disclosure updater")
  elif news_events.get("ok") is not True or str(news_events.get("status", "")).lower() != "ok":
    errors.append("news_events.json official disclosure refresh is not successful")
  if not news_items:
    errors.append("news_events.json contains no official disclosures")
  news_sources = news_events.get("source_status", []) if isinstance(news_events, dict) else []
  if len(news_sources) != 2 or any(
      not isinstance(source, dict) or source.get("status") != "ok" or int(source.get("rows") or 0) <= 0
      for source in news_sources
  ):
    errors.append("news_events.json does not contain successful TWSE and TPEx source status")
  for item in news_items:
    if not isinstance(item, dict):
      errors.append("news_events.json contains a non-object event")
      break
    source_url = str(item.get("source_url") or "")
    stocks = item.get("stocks")
    if (
        not item.get("title")
        or not source_url.startswith(("https://openapi.twse.com.tw/", "https://www.tpex.org.tw/"))
        or item.get("news_score") is not None
        or item.get("score_status") != "未評分"
        or not isinstance(stocks, list)
        or not stocks
    ):
      errors.append(f"news_events.json contains an invalid or scored event: {item.get('id') or '--'}")
      break

  if isinstance(data_status, dict):
    for item in data_status.get("each_file_status", []):
      if not isinstance(item, dict):
        continue
      status = str(item.get("status", "")).lower()
      file_name = item.get("file", "unknown file")
      if status in {"failed", "missing"}:
        errors.append(f"{file_name} status={status}: {item.get('failed_reasons') or item.get('error') or ''}")
      elif status == "stale":
        errors.append(f"{file_name} status=stale: {item.get('failed_reasons') or item.get('error') or ''}")
    for warning in data_status.get("warning", []):
      warnings.append(str(warning))

  for warning in warnings:
    print(f"WARNING: {warning}")
  for error in errors:
    print(f"ERROR: {error}")

  if errors and args.strict:
    return 1
  print("Site data validation passed." if not errors else "Site data validation completed with errors.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
