#!/usr/bin/env python
"""Validate unified ASURADA site data before committing/deploying."""

from __future__ import annotations

import argparse
import json
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
FACTOR_STATUS = DOCS_PROCESSED / "factor-scores.status.json"
FACTOR_SCORES = DOCS_PROCESSED / "factor-scores.json"


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
    "updated_at",
    "updatedAt",
  ))
  if value:
    return normalize_date(value)
  items = get_items(payload)
  if items and isinstance(items[0], dict):
    return normalize_date(first_existing(
      items[0],
      ("latest_trade_date", "trade_date", "market_date", "date", "dataDate", "data_date", "updatedAt", "updated_at"),
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

  required = [SITE_META, DATA_STATUS, RADAR_JSON, STOCK_METRICS, FACTOR_STATUS, FACTOR_SCORES]
  if not all(ensure_exists(path, errors) for path in required):
    for error in errors:
      print(f"ERROR: {error}")
    return 1 if args.strict else 0

  site_meta = read_json(SITE_META)
  data_status = read_json(DATA_STATUS)
  radar = read_json(RADAR_JSON)
  stock_metrics = read_json(STOCK_METRICS)
  factor_status = read_json(FACTOR_STATUS)
  factor_scores = read_json(FACTOR_SCORES)

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

  if isinstance(factor_status, dict):
    if factor_status.get("ok") is False:
      errors.append(f"factor-scores.status.json ok=false: {factor_status.get('failed_reasons') or factor_status.get('message') or 'unknown reason'}")
    if factor_status.get("previous_data_preserved"):
      errors.append("factor-scores.status.json preserved previous data after a failed refresh")

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
