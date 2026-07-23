#!/usr/bin/env python
"""Refresh official market history and AI Top 10 post-signal validation."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from ai_validation import (
        OUTPUT_FILENAMES,
        SUPPORT_FILENAME,
        VALIDATION_VERSION,
        _atomic_write_json,
        build_validation_bundle,
        failed_status_payload,
        market_key,
        now_taipei,
        number,
        read_json,
        valid_iso_date,
        write_bundle_transactional,
    )
    from official_daily_quotes import (
        fetch_daily_quotes_exact,
        fetch_taiex_month,
    )
    from update_factor_scores import parse_quote_rows
except ModuleNotFoundError:  # pragma: no cover - package import for tests.
    from scripts.ai_validation import (
        OUTPUT_FILENAMES,
        SUPPORT_FILENAME,
        VALIDATION_VERSION,
        _atomic_write_json,
        build_validation_bundle,
        failed_status_payload,
        market_key,
        now_taipei,
        number,
        read_json,
        valid_iso_date,
        write_bundle_transactional,
    )
    from scripts.official_daily_quotes import (
        fetch_daily_quotes_exact,
        fetch_taiex_month,
    )
    from scripts.update_factor_scores import parse_quote_rows


ROOT = Path(__file__).resolve().parents[1]
DATA_PROCESSED = ROOT / "data" / "processed"
DOCS_PROCESSED = ROOT / "docs" / "data" / "processed"
TOP10_HISTORY = ROOT / "data" / "history" / "ai-top10"
VALIDATION_HISTORY = ROOT / "data" / "history" / "ai-validation"
FACTOR_QUOTE_HISTORY = DATA_PROCESSED / "factor-quote-history.json"
FACTOR_STATUS_PATH = DATA_PROCESSED / "factor-scores.status.json"
STOCK_MASTER_PATH = DATA_PROCESSED / "stocks_master.json"
CACHE_PATH = DATA_PROCESSED / SUPPORT_FILENAME
DOCS_CACHE_PATH = DOCS_PROCESSED / SUPPORT_FILENAME
STATUS_PATH = DATA_PROCESSED / "ai-validation-status.json"
DOCS_STATUS_PATH = DOCS_PROCESSED / "ai-validation-status.json"
DETAIL_PATH = DATA_PROCESSED / "ai-validation-detail.json"
# Absence is interpreted as an official no-quote day only after a response is
# effectively full-market. This threshold is deliberately much stricter than
# the 80% health gate used by factor scoring: current normal TWSE/TPEx payloads
# cover about 99.8% of the stock master.
MIN_FULL_MARKET_COVERAGE_RATIO = 0.997


def load_top10_snapshots(path: Path = TOP10_HISTORY) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for file in sorted(path.glob("*.json")) if path.exists() else []:
        try:
            payload = json.loads(file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise ValueError(f"invalid immutable Top 10 snapshot {file.name}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"immutable Top 10 snapshot {file.name} is not an object")
        snapshot_date = valid_iso_date(
            payload.get("dataDate")
            or payload.get("latest_trade_date")
            or file.stem
        )
        items = payload.get("items")
        if not snapshot_date or file.stem != snapshot_date:
            raise ValueError(f"immutable Top 10 snapshot {file.name} has a mismatched date")
        if payload.get("ok") is not True:
            raise ValueError(f"immutable Top 10 snapshot {file.name} is not successful")
        if not isinstance(items, list) or len(items) != 10:
            raise ValueError(f"immutable Top 10 snapshot {file.name} must contain exactly 10 rows")
        codes = [
            str(item.get("code") or item.get("symbol") or "")
            for item in items
            if isinstance(item, dict)
        ]
        if len(codes) != 10 or len(set(codes)) != 10 or any(not code for code in codes):
            raise ValueError(f"immutable Top 10 snapshot {file.name} has duplicate or invalid codes")
        snapshots.append(payload)
    return snapshots


def _month_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date[:7] + "-01", "%Y-%m-%d").date()
    end = datetime.strptime(end_date[:7] + "-01", "%Y-%m-%d").date()
    months: list[str] = []
    current = start
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        current = date(current.year + (1 if current.month == 12 else 0), 1 if current.month == 12 else current.month + 1, 1)
    return months


def _tracked_stocks(snapshots: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Return every immutable market observed for each historical symbol."""
    tracked: dict[str, set[str]] = {}
    for snapshot in snapshots:
        for item in snapshot.get("items") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("symbol") or "").strip()
            market = market_key(item.get("market"))
            if code and market:
                tracked.setdefault(code, set()).add(market)
    return tracked


def _latest_tracked_markets(
    snapshots: list[dict[str, Any]],
) -> dict[str, str]:
    latest: dict[str, tuple[str, str]] = {}
    for snapshot in snapshots:
        snapshot_date = valid_iso_date(
            snapshot.get("dataDate")
            or snapshot.get("latest_trade_date")
            or snapshot.get("latestTradeDate")
        )
        if not snapshot_date:
            continue
        for item in snapshot.get("items") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("symbol") or "").strip()
            market = market_key(item.get("market"))
            if code and market and snapshot_date >= latest.get(code, ("", ""))[0]:
                latest[code] = (snapshot_date, market)
    return {code: value[1] for code, value in latest.items()}


def _market_reference_counts(
    stock_master: Any,
    factor_status: Any,
) -> dict[str, dict[str, int]]:
    """Build conservative full-market row requirements from trusted local metadata."""
    raw_items = stock_master.get("items") if isinstance(stock_master, dict) else stock_master
    master_counts = {"twse": 0, "tpex": 0}
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            market = market_key(item.get("market"))
            if market in master_counts:
                master_counts[market] += 1

    factor_status = factor_status if isinstance(factor_status, dict) else {}
    previous_counts = {
        "twse": max(0, int(number(factor_status.get("twse_quote_matched")) or 0)),
        "tpex": max(0, int(number(factor_status.get("tpex_quote_matched")) or 0)),
    }
    result: dict[str, dict[str, int]] = {}
    for market in ("twse", "tpex"):
        reference = max(master_counts[market], previous_counts[market])
        result[market] = {
            "masterRows": master_counts[market],
            "previousMatchedRows": previous_counts[market],
            "referenceRows": reference,
            "requiredRows": (
                math.ceil(reference * MIN_FULL_MARKET_COVERAGE_RATIO)
                if reference > 0
                else 0
            ),
        }
    return result


def _load_market_reference_counts() -> dict[str, dict[str, int]]:
    return _market_reference_counts(
        read_json(STOCK_MASTER_PATH, {}),
        read_json(FACTOR_STATUS_PATH, {}),
    )


def _assess_full_market_coverage(
    market: str,
    parsed_quote_count: int,
    reference: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reject partial/empty responses before absence can mean suspension."""
    reference = reference if isinstance(reference, dict) else {}
    required = max(0, int(number(reference.get("requiredRows")) or 0))
    parsed = max(0, int(parsed_quote_count))
    ok = required > 0 and parsed >= required
    if required <= 0:
        error = f"{market.upper()} full-market reference population unavailable"
    elif parsed < required:
        error = (
            f"{market.upper()} exact daily response is incomplete: "
            f"parsed={parsed}, required>={required}"
        )
    else:
        error = ""
    return {
        "ok": ok,
        "coverageVerified": ok,
        "parsedRows": parsed,
        "requiredRows": required,
        "referenceRows": max(0, int(number(reference.get("referenceRows")) or 0)),
        "masterRows": max(0, int(number(reference.get("masterRows")) or 0)),
        "previousMatchedRows": max(
            0, int(number(reference.get("previousMatchedRows")) or 0)
        ),
        "error": error,
    }


def _bar_from_quote(
    quote: dict[str, Any],
    trade_date: str,
    source: str,
    market: str,
) -> dict[str, Any]:
    open_price = number(quote.get("open_price"))
    close = number(quote.get("trade_price"))
    volume = number(quote.get("volume"))
    transactions = number(quote.get("transactions"))
    has_trade = bool(
        close is not None
        and close > 0
        and (
            (volume is not None and volume > 0)
            or (transactions is not None and transactions > 0)
        )
    )
    return {
        "date": trade_date,
        "market": market,
        "rawPresent": True,
        "hasTrade": has_trade,
        "open": open_price,
        "high": number(quote.get("high_price")),
        "low": number(quote.get("low_price")),
        "close": close,
        "volume": int(volume) if volume is not None else None,
        "transactions": int(transactions) if transactions is not None else None,
        "source": source,
    }


def _bar_from_factor_history(
    row: dict[str, Any],
    market: str,
) -> dict[str, Any] | None:
    trade_date = valid_iso_date(row.get("date"))
    if not trade_date or number(row.get("open")) is None or number(row.get("close")) is None:
        return None
    volume = number(row.get("volume"))
    transactions = number(row.get("transactions"))
    return {
        "date": trade_date,
        "market": market,
        "rawPresent": True,
        "hasTrade": bool(
            number(row.get("close")) is not None
            and number(row.get("close")) > 0
            and (
                (volume is not None and volume > 0)
                or (transactions is not None and transactions > 0)
            )
        ),
        "open": number(row.get("open")),
        "high": number(row.get("high")),
        "low": number(row.get("low")),
        "close": number(row.get("close")),
        "volume": int(volume) if volume is not None else None,
        "transactions": int(transactions) if transactions is not None else None,
        "source": row.get("source") or "factor-quote-history official daily quotes",
    }


def _market_from_source(value: Any) -> str:
    source = str(value or "").lower()
    if "twse.com.tw" in source:
        return "twse"
    if "tpex.org.tw" in source:
        return "tpex"
    return ""


def refresh_market_cache(
    snapshots: list[dict[str, Any]],
    existing: dict[str, Any],
    *,
    as_of_date: str,
    allow_network: bool = True,
    market_references: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    tracked = _tracked_stocks(snapshots)
    latest_markets = _latest_tracked_markets(snapshots)
    market_references = market_references or _load_market_reference_counts()
    signal_dates = sorted(
        valid_iso_date(
            snapshot.get("dataDate")
            or snapshot.get("latest_trade_date")
            or snapshot.get("latestTradeDate")
        )
        for snapshot in snapshots
    )
    signal_dates = [value for value in signal_dates if value]
    if not signal_dates:
        raise ValueError("no valid immutable AI Top 10 signal dates")
    earliest_signal = signal_dates[0]

    cache = dict(existing) if isinstance(existing, dict) else {}
    benchmark_map = {
        valid_iso_date(row.get("date")): dict(row)
        for row in cache.get("benchmark") or []
        if isinstance(row, dict)
        and valid_iso_date(row.get("date"))
        and valid_iso_date(row.get("date")) <= as_of_date
    }
    existing_coverage = (
        cache.get("coverage") if isinstance(cache.get("coverage"), dict) else {}
    )
    coverage: dict[str, dict[str, dict[str, Any]]] = {"twse": {}, "tpex": {}}
    for market in ("twse", "tpex"):
        for trade_date, raw_row in dict(existing_coverage.get(market) or {}).items():
            normalized_date = valid_iso_date(trade_date)
            if (
                not normalized_date
                or normalized_date > as_of_date
                or not isinstance(raw_row, dict)
            ):
                continue
            row = dict(raw_row)
            # Legacy cache entries only proved that tracked symbols happened to
            # be present. They may not turn an absent symbol into a suspension.
            if row.get("ok") and not row.get("coverageVerified"):
                row["ok"] = False
                row["error"] = "legacy market coverage was not full-market verified"
            coverage[market][normalized_date] = row

    stock_maps: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
        code: {market: {} for market in markets}
        for code, markets in tracked.items()
    }
    existing_stocks = cache.get("stocks") if isinstance(cache.get("stocks"), dict) else {}
    for code, markets in tracked.items():
        stock = existing_stocks.get(code) if isinstance(existing_stocks, dict) else None
        if not isinstance(stock, dict):
            continue
        legacy_market = market_key(stock.get("market"))
        raw_bars: list[Any] = list(stock.get("bars") or [])
        bars_by_market = stock.get("barsByMarket")
        if isinstance(bars_by_market, dict):
            for market, rows in bars_by_market.items():
                normalized_market = market_key(market)
                if normalized_market not in markets or not isinstance(rows, list):
                    continue
                raw_bars.extend(
                    {**row, "market": normalized_market}
                    for row in rows
                    if isinstance(row, dict)
                )
        for raw_bar in raw_bars:
            if not isinstance(raw_bar, dict):
                continue
            trade_date = valid_iso_date(raw_bar.get("date"))
            if not trade_date or trade_date > as_of_date:
                continue
            bar_market = market_key(raw_bar.get("market")) or legacy_market
            if not bar_market and len(markets) == 1:
                bar_market = next(iter(markets))
            if bar_market not in markets:
                continue
            stock_maps[code][bar_market][trade_date] = {
                **raw_bar,
                "date": trade_date,
                "market": bar_market,
            }

    # Reuse current-day official OHLC already fetched by factor scoring.
    factor_history = read_json(FACTOR_QUOTE_HISTORY, {})
    history_items = factor_history.get("items") if isinstance(factor_history, dict) else {}
    if isinstance(history_items, dict):
        for code, markets in tracked.items():
            for row in history_items.get(code) or []:
                if not isinstance(row, dict):
                    continue
                row_market = (
                    market_key(row.get("market"))
                    or _market_from_source(row.get("source"))
                )
                if not row_market and len(markets) == 1:
                    row_market = next(iter(markets))
                if row_market not in markets:
                    # Ambiguous legacy rows are not safe to assign across a
                    # listing-market transition. Exact daily fetch fills them.
                    continue
                bar = _bar_from_factor_history(row, row_market)
                if bar and earliest_signal < bar["date"] <= as_of_date:
                    stock_maps[code][row_market][bar["date"]] = bar

    source_status: list[dict[str, Any]] = []
    if allow_network:
        for month in _month_range(earliest_signal, as_of_date):
            try:
                bars, source = fetch_taiex_month(month)
                accepted = 0
                for row in bars:
                    trade_date = valid_iso_date(row.get("date"))
                    if not trade_date or trade_date > as_of_date:
                        continue
                    benchmark_map[trade_date] = {
                        "date": trade_date,
                        "open": number(row.get("open")),
                        "high": number(row.get("high")),
                        "low": number(row.get("low")),
                        "close": number(row.get("close")),
                        "source": row.get("source") or source,
                    }
                    accepted += 1
                source_status.append(
                    {
                        "source": "TWSE TAIEX MI_5MINS_HIST",
                        "period": month,
                        "ok": True,
                        "rows": accepted,
                        "url": source,
                        "error": "",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - cached official bars remain usable.
                source_status.append(
                    {
                        "source": "TWSE TAIEX MI_5MINS_HIST",
                        "period": month,
                        "ok": False,
                        "rows": 0,
                        "url": "",
                        "error": str(exc),
                    }
                )

    calendar = sorted(
        trade_date
        for trade_date, bar in benchmark_map.items()
        if earliest_signal <= trade_date <= as_of_date
        and all(number(bar.get(field)) is not None for field in ("open", "high", "low", "close"))
    )
    if allow_network:
        by_market = {
            market: sorted(code for code, markets in tracked.items() if market in markets)
            for market in ("twse", "tpex")
        }
        for trade_date in (value for value in calendar if value > earliest_signal):
            for market, codes in by_market.items():
                if not codes:
                    continue
                already_complete = all(
                    trade_date in stock_maps[code][market] for code in codes
                )
                if already_complete:
                    continue
                try:
                    raw_rows, source_date, source_url = fetch_daily_quotes_exact(market, trade_date)
                    label = "上市" if market == "twse" else "上櫃"
                    quotes, parsed_date = parse_quote_rows(raw_rows, label, source_url)
                    if source_date != trade_date or parsed_date != trade_date:
                        raise ValueError(
                            f"{market.upper()} exact history date mismatch: "
                            f"requested={trade_date}, source={source_date}, parsed={parsed_date}"
                        )
                    assessment = _assess_full_market_coverage(
                        market,
                        len(quotes),
                        market_references.get(market),
                    )
                    # Present official rows remain usable even when a response
                    # is too small to prove that an omission means suspension.
                    for code in codes:
                        quote = quotes.get(code)
                        if quote:
                            stock_maps[code][market][trade_date] = _bar_from_quote(
                                quote, trade_date, source_url, market
                            )
                        elif assessment["ok"]:
                            stock_maps[code][market][trade_date] = {
                                "date": trade_date,
                                "market": market,
                                "rawPresent": False,
                                "hasTrade": False,
                                "open": None,
                                "high": None,
                                "low": None,
                                "close": None,
                                "volume": None,
                                "transactions": None,
                                "source": source_url,
                            }
                    coverage[market][trade_date] = {
                        **assessment,
                        "source": source_url,
                        "rows": len(quotes),
                        "rawRows": len(raw_rows),
                    }
                    source_status.append(
                        {
                            "source": f"{market.upper()} exact daily quotes",
                            "period": trade_date,
                            "ok": assessment["ok"],
                            "rows": len(quotes),
                            "url": source_url,
                            "error": assessment["error"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - expose the exact coverage gap.
                    previous = coverage[market].get(trade_date)
                    if not (
                        isinstance(previous, dict)
                        and previous.get("ok")
                        and previous.get("coverageVerified")
                    ):
                        coverage[market][trade_date] = {
                            "ok": False,
                            "coverageVerified": False,
                            "source": "",
                            "rows": 0,
                            "error": str(exc),
                        }
                    source_status.append(
                        {
                            "source": f"{market.upper()} exact daily quotes",
                            "period": trade_date,
                            "ok": False,
                            "rows": 0,
                            "url": "",
                            "error": str(exc),
                        }
                    )

        required_dates = [value for value in calendar if value > earliest_signal]
        if not required_dates:
            benchmark_attempts = [
                row
                for row in source_status
                if row.get("source") == "TWSE TAIEX MI_5MINS_HIST"
            ]
            if benchmark_attempts and not any(row.get("ok") for row in benchmark_attempts):
                raise RuntimeError(
                    "official TAIEX post-signal calendar is unavailable and cache has no "
                    "post-signal trading session"
                )

        unavailable: list[str] = []
        for trade_date in required_dates:
            for market, codes in by_market.items():
                if not codes:
                    continue
                market_coverage = coverage[market].get(trade_date)
                verified = bool(
                    isinstance(market_coverage, dict)
                    and market_coverage.get("ok")
                    and market_coverage.get("coverageVerified")
                )
                any_cached_bar = any(
                    trade_date in stock_maps[code][market] for code in codes
                )
                if not verified and not any_cached_bar:
                    unavailable.append(f"{market.upper()} {trade_date}")
        if unavailable:
            raise RuntimeError(
                "required post-signal official market data unavailable without cache: "
                + ", ".join(unavailable)
            )

    return {
        "schemaVersion": 1,
        "validationVersion": VALIDATION_VERSION,
        "updatedAt": now_taipei().isoformat(),
        "asOfDate": as_of_date,
        "earliestSignalDate": earliest_signal,
        "calendar": calendar,
        "benchmarkCode": "TAIEX",
        "benchmark": [benchmark_map[key] for key in sorted(benchmark_map) if key <= as_of_date],
        "stocks": {
            code: {
                "market": latest_markets.get(code) or sorted(tracked[code])[0],
                "markets": sorted(tracked[code]),
                "barsByMarket": {
                    market: [
                        stock_maps[code][market][key]
                        for key in sorted(stock_maps[code][market])
                    ]
                    for market in sorted(tracked[code])
                },
                "bars": sorted(
                    (
                        row
                        for market in sorted(tracked[code])
                        for row in stock_maps[code][market].values()
                    ),
                    key=lambda row: (str(row.get("date") or ""), str(row.get("market") or "")),
                ),
            }
            for code in sorted(tracked)
        },
        "coverage": coverage,
        "sourceStatus": source_status,
        "sources": {
            "benchmark": "TWSE TAIEX MI_5MINS_HIST",
            "twse": "TWSE MI_INDEX exact-date daily quotes",
            "tpex": "TPEx exact-date daily quotes",
        },
    }


def _restore_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def write_outputs(
    cache: dict[str, Any],
    payloads: dict[str, dict[str, Any]],
) -> Path:
    latest = (
        payloads["ai-validation-detail.json"].get("latestPriceDate")
        or payloads["ai-validation-detail.json"].get("latestSignalDate")
    )
    history_path = VALIDATION_HISTORY / f"{latest}.json"
    paths = [
        directory / name
        for directory in (DATA_PROCESSED, DOCS_PROCESSED)
        for name in OUTPUT_FILENAMES
    ] + [CACHE_PATH, DOCS_CACHE_PATH, history_path]
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        _atomic_write_json(CACHE_PATH, cache)
        _atomic_write_json(DOCS_CACHE_PATH, cache)
        return write_bundle_transactional(
            payloads,
            DATA_PROCESSED,
            DOCS_PROCESSED,
            VALIDATION_HISTORY,
        )
    except Exception:
        _restore_files(before)
        raise


def run(as_of_date: str | None = None, allow_network: bool = True) -> int:
    attempted_at = now_taipei().isoformat()
    previous_status = read_json(STATUS_PATH, {})
    try:
        snapshots = load_top10_snapshots()
        if not snapshots:
            raise ValueError("data/history/ai-top10 contains no valid immutable Top 10 snapshots")
        target = valid_iso_date(as_of_date) or now_taipei().date().isoformat()
        existing_cache = read_json(CACHE_PATH, {})
        cache = refresh_market_cache(
            snapshots,
            existing_cache,
            as_of_date=target,
            allow_network=allow_network,
        )
        payloads = build_validation_bundle(
            snapshots,
            cache,
            existing_detail=read_json(DETAIL_PATH, {}),
            generated_at=attempted_at,
        )
        history_path = write_outputs(cache, payloads)
    except Exception as exc:  # noqa: BLE001 - preserve normal outputs, update failure status only.
        reason = f"AI performance validation update failed: {exc}"
        failed = failed_status_payload(reason, previous_status, attempted_at)
        _atomic_write_json(STATUS_PATH, failed)
        _atomic_write_json(DOCS_STATUS_PATH, failed)
        print(reason)
        print("previous validation outputs preserved")
        return 1

    status = payloads["ai-validation-status.json"]
    print(f"AI validation: {status['status']}")
    print(f"latest signal date: {status.get('latestSignalDate') or '--'}")
    print(f"latest entry date: {status.get('latestEntryDate') or '--'}")
    print(f"signals: {len(payloads['ai-validation-detail.json']['items'])}")
    print(f"D+20 completed: {status['d20CompletedSignals']}")
    print(f"history snapshot: {history_path.relative_to(ROOT)}")
    for warning in status.get("warnings") or []:
        print(f"- {warning}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", help="Taipei cutoff date, YYYY-MM-DD.")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Build from the existing official cache without fetching sources.",
    )
    args = parser.parse_args()
    return run(args.as_of_date, allow_network=not args.no_network)


if __name__ == "__main__":
    raise SystemExit(main())
