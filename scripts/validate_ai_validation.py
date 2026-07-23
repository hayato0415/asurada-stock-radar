#!/usr/bin/env python
"""Strictly validate AI post-signal performance outputs and source invariants."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from ai_validation import (
        OUTPUT_FILENAMES,
        PERIODS,
        SUPPORT_FILENAME,
        VALIDATION_VERSION,
        build_validation_bundle,
        number,
        read_json,
        valid_iso_date,
    )
    from update_ai_validation import load_top10_snapshots
except ModuleNotFoundError:  # pragma: no cover
    from scripts.ai_validation import (
        OUTPUT_FILENAMES,
        PERIODS,
        SUPPORT_FILENAME,
        VALIDATION_VERSION,
        build_validation_bundle,
        number,
        read_json,
        valid_iso_date,
    )
    from scripts.update_ai_validation import load_top10_snapshots


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
DOCS = ROOT / "docs" / "data" / "processed"
CACHE = DATA / SUPPORT_FILENAME
CODE_PATTERN = re.compile(r"^\d{4,6}$")
UNIFIED_WRAPPER_KEYS = {
    "run_id",
    "generated_at",
    "latest_trade_date",
    "data_version",
    "source_pipeline",
}


def _load(path: Path, errors: list[str]) -> Any:
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        errors.append(f"invalid JSON {path.relative_to(ROOT)}: {exc}")
        return {}


def _validate_periods(item: dict[str, Any], errors: list[str]) -> None:
    signal_id = item.get("signalId") or "--"
    completed = set(item.get("completedPeriods") or [])
    pending = set(item.get("pendingPeriods") or [])
    if completed & pending:
        errors.append(f"{signal_id}: period cannot be both completed and pending")
    for period in PERIODS:
        label = f"D+{period}"
        prefix = f"d{period}"
        trade_date = item.get(f"{prefix}TradeDate")
        close = item.get(f"{prefix}Close")
        result = item.get(f"{prefix}Return")
        if label in completed:
            if not valid_iso_date(trade_date) or number(close) is None or number(result) is None:
                errors.append(f"{signal_id}: completed {label} has null date/close/return")
        elif label in pending:
            if trade_date is not None or close is not None or result is not None:
                errors.append(f"{signal_id}: pending {label} must remain null")
        else:
            errors.append(f"{signal_id}: {label} missing from completed/pending periods")


def _validate_detail(detail: dict[str, Any], errors: list[str]) -> None:
    if detail.get("validationVersion") != VALIDATION_VERSION:
        errors.append("detail validationVersion mismatch")
    items = detail.get("items")
    if not isinstance(items, list) or not items:
        errors.append("detail items must be a non-empty array")
        return
    signal_ids = [str(item.get("signalId") or "") for item in items if isinstance(item, dict)]
    if len(signal_ids) != len(set(signal_ids)) or any(not value for value in signal_ids):
        errors.append("detail contains duplicate or blank signalId")
    for item in items:
        if not isinstance(item, dict):
            errors.append("detail contains a non-object signal")
            continue
        signal_id = item.get("signalId") or "--"
        if item.get("signalMode") != "first_entry":
            errors.append(f"{signal_id}: main detail item is not first_entry mode")
        if not CODE_PATTERN.fullmatch(str(item.get("code") or "")):
            errors.append(f"{signal_id}: invalid production stock code")
        signal_date = valid_iso_date(item.get("signalDate"))
        if not signal_date:
            errors.append(f"{signal_id}: invalid signalDate")
        if item.get("entryPriceAvailable"):
            entry_date = valid_iso_date(item.get("entryTradeDate"))
            if not entry_date or entry_date <= signal_date:
                errors.append(f"{signal_id}: entryTradeDate must be after signalDate")
            if number(item.get("entryOpen")) is None or number(item.get("entryOpen")) <= 0:
                errors.append(f"{signal_id}: entryPriceAvailable requires a positive entryOpen")
            if not item.get("entryPriceSource"):
                errors.append(f"{signal_id}: entryPriceSource is missing")
        else:
            if item.get("entryOpen") is not None or item.get("entryTradeDate") is not None:
                errors.append(f"{signal_id}: unavailable entry must remain null")
        if item.get("d1TradeDate") and item.get("d1TradeDate") != item.get("entryTradeDate"):
            errors.append(f"{signal_id}: D+1 must be the entry-day close")
        _validate_periods(item, errors)

    daily = detail.get("dailyObservations")
    if not isinstance(daily, list):
        errors.append("detail dailyObservations must be an array")
    else:
        daily_ids = [str(item.get("signalId") or "") for item in daily if isinstance(item, dict)]
        if len(daily_ids) != len(set(daily_ids)):
            errors.append("daily observation mode contains duplicate signalId")


def _validate_summary(summary: dict[str, Any], detail: dict[str, Any], errors: list[str]) -> None:
    items = detail.get("items") if isinstance(detail.get("items"), list) else []
    if summary.get("eventMode") != "first_entry":
        errors.append("summary must use first_entry mode")
    if summary.get("totalSignals") != len(items):
        errors.append("summary totalSignals does not match detail")
    expected_tracking = sum(
        item.get("trackingStatus") != "completed"
        for item in items
    )
    if summary.get("trackingSignals") != expected_tracking:
        errors.append("summary trackingSignals does not match unfinished signals")
    periods = summary.get("periods")
    if not isinstance(periods, list) or len(periods) != len(PERIODS):
        errors.append("summary periods must contain D+1/D+3/D+5/D+10/D+20")
        return
    by_label = {row.get("period"): row for row in periods if isinstance(row, dict)}
    for period in PERIODS:
        label = f"D+{period}"
        expected = sum(item.get(f"d{period}Return") is not None for item in items)
        row = by_label.get(label)
        if not row or row.get("completedSamples") != expected:
            errors.append(f"summary {label} denominator includes pending or missing samples")


def _validate_portfolio(portfolio: dict[str, Any], errors: list[str]) -> None:
    cost = portfolio.get("costAssumption")
    if not isinstance(cost, dict) or cost.get("grossReturnIncludesCosts") is not False:
        errors.append("portfolio gross/net cost assumptions are missing")
    for key in ("holding5", "holding20"):
        curve = portfolio.get(key)
        if not isinstance(curve, dict):
            errors.append(f"portfolio {key} is missing")
            continue
        rows = curve.get("rows")
        if not isinstance(rows, list):
            errors.append(f"portfolio {key}.rows must be an array")
            continue
        dates = [row.get("date") for row in rows if isinstance(row, dict)]
        if dates != sorted(set(dates)):
            errors.append(f"portfolio {key} dates are duplicate or unsorted")


def _validate_factor(factor: dict[str, Any], errors: list[str]) -> None:
    for mode in ("firstEntry", "dailyObservation"):
        payload = factor.get(mode)
        if not isinstance(payload, dict) or payload.get("mode") not in {
            "first_entry",
            "daily_observation",
        }:
            errors.append(f"factor performance {mode} mode is missing")
            continue
        groups = payload.get("groups")
        versions = groups.get("scoreVersions") if isinstance(groups, dict) else None
        if not isinstance(versions, list):
            errors.append(f"factor performance {mode} score versions are not separated")


def _validate_status(status: dict[str, Any], detail: dict[str, Any], errors: list[str]) -> None:
    if status.get("ok") is not True or status.get("status") not in {"ok", "warning"}:
        errors.append("ai-validation-status is not a successful current run")
    if status.get("previousDataPreserved") is not False:
        errors.append("ai-validation-status says previous data was preserved")
    if status.get("pipelineIntegrated") is not True:
        errors.append("AI validation is not marked as integrated into the unified pipeline")
    if status.get("validationVersion") != VALIDATION_VERSION:
        errors.append("status validationVersion mismatch")
    items = detail.get("items") if isinstance(detail.get("items"), list) else []
    expected_d20 = sum(item.get("d20Return") is not None for item in items)
    if status.get("d20CompletedSignals") != expected_d20:
        errors.append("status D+20 completed count does not match detail")


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop only metadata injected later by the unified site wrapper."""
    return {
        key: value
        for key, value in payload.items()
        if key not in UNIFIED_WRAPPER_KEYS
    }


def main() -> int:
    errors: list[str] = []
    payloads: dict[str, Any] = {}
    for name in (*OUTPUT_FILENAMES, SUPPORT_FILENAME):
        root_path = DATA / name
        docs_path = DOCS / name
        payloads[name] = _load(root_path, errors)
        _load(docs_path, errors)
        if root_path.exists() and docs_path.exists() and root_path.read_bytes() != docs_path.read_bytes():
            errors.append(f"root/docs mirror mismatch: {name}")

    detail = payloads.get("ai-validation-detail.json")
    summary = payloads.get("ai-validation-summary.json")
    portfolio = payloads.get("ai-validation-portfolio.json")
    factor = payloads.get("ai-factor-performance.json")
    status = payloads.get("ai-validation-status.json")
    cache = payloads.get(SUPPORT_FILENAME)
    for name, payload in (
        ("detail", detail),
        ("summary", summary),
        ("portfolio", portfolio),
        ("factor", factor),
        ("status", status),
        ("market history", cache),
    ):
        if not isinstance(payload, dict):
            errors.append(f"{name} payload must be an object")

    if all(isinstance(payload, dict) for payload in (detail, summary, portfolio, factor, status, cache)):
        _validate_detail(detail, errors)
        _validate_summary(summary, detail, errors)
        _validate_portfolio(portfolio, errors)
        _validate_factor(factor, errors)
        _validate_status(status, detail, errors)

        # Rebuild from immutable snapshots and the official cache. This catches
        # signal-close entries, natural-day horizons, forward fills, duplicated
        # cycles, and any front-looking mutation in one deterministic check.
        snapshots = load_top10_snapshots()
        try:
            expected = build_validation_bundle(
                snapshots,
                cache,
                existing_detail={},
                generated_at=detail.get("generatedAt"),
            )
            actual_outputs = {
                "ai-validation-detail.json": detail,
                "ai-validation-summary.json": summary,
                "ai-validation-portfolio.json": portfolio,
                "ai-factor-performance.json": factor,
                "ai-validation-status.json": status,
            }
            for name in OUTPUT_FILENAMES:
                actual = actual_outputs[name]
                if _semantic_payload(actual) != _semantic_payload(expected[name]):
                    errors.append(
                        f"{name} does not reproduce from immutable snapshots "
                        "and official price cache"
                    )
        except Exception as exc:
            errors.append(f"deterministic validation rebuild failed: {exc}")

    if errors:
        print("AI validation strict check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("AI validation strict check passed.")
    print(f"signals: {len(detail.get('items') or [])}")
    print(f"latest signal date: {detail.get('latestSignalDate') or '--'}")
    print(f"latest price date: {detail.get('latestPriceDate') or '--'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
