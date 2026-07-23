#!/usr/bin/env python
"""Build post-signal performance validation from immutable AI Top 10 snapshots.

The production rules are intentionally centralized here:

* Entry is the first valid individual-stock trading day's open after a signal.
* D+1 is the entry-day close. D+N is the Nth valid individual-stock
  trading day's close counting the entry day as day one.
* Missing official prices stay ``None``. A prior close is never carried
  forward and the signal-day close is never used as the executable entry.
* First-entry signal cycles and daily-observation research records are built
  and summarized separately.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


TAIPEI = timezone(timedelta(hours=8))
VALIDATION_VERSION = "ai-validation-v1"
BENCHMARK_CODE = "TAIEX"
BENCHMARK_NAME = "發行量加權股價指數"

# Signal-cycle rules. A one-trading-day gap remains the same cycle; two or
# more confirmed missing trading days or a completed D+20 creates a new
# independent signal. A score-version deployment alone must not open an
# overlapping trade while the original first-entry cycle is still active.
SIGNAL_GAP_TOLERANCE = 1
NEW_SIGNAL_AFTER_TRADING_DAYS = 2
MAX_HOLDING_DAYS = 20

PERIODS = (1, 3, 5, 10, 20)
ABSOLUTE_SUCCESS_THRESHOLD = 0.0
MAX_ACCEPTABLE_MAE_20 = -10.0

FACTOR_HIGH_THRESHOLD = 75.0
FACTOR_MEDIUM_THRESHOLD = 50.0
MIN_NORMAL_SAMPLE = 30
MIN_OBSERVATION_SAMPLE = 10

# Standard Taiwan cash-equity assumptions. They are disclosed in every
# portfolio payload and never hidden in front-end calculations.
BUY_COMMISSION_RATE = 0.001425
SELL_COMMISSION_RATE = 0.001425
SELL_TRANSACTION_TAX_RATE = 0.003
MINIMUM_COMMISSION_INCLUDED = False

OUTPUT_FILENAMES = (
    "ai-validation-detail.json",
    "ai-validation-summary.json",
    "ai-validation-portfolio.json",
    "ai-factor-performance.json",
    "ai-validation-status.json",
)
SUPPORT_FILENAME = "ai-validation-market-history.json"

IMMUTABLE_SIGNAL_FIELDS = (
    "signalDate",
    "code",
    "name",
    "market",
    "industry",
    "concepts",
    "scoreVersion",
    "signalRank",
    "signalScore",
    "fundamentalScore",
    "technicalScore",
    "chipScore",
    "turnoverScore",
    "signalClose",
    "changePercent",
    "tradeType",
    "riskLabel",
    "entryStatus",
)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI).replace(microsecond=0)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def number(value: Any) -> float | None:
    if value in (None, "", "--", "---", "N/A", "null"):
        return None
    try:
        parsed = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def rounded(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def valid_iso_date(value: Any) -> str:
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def market_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"twse", "listed", "上市"} or "上市" in text:
        return "twse"
    if text in {"tpex", "otc", "上櫃"} or "上櫃" in text:
        return "tpex"
    return ""


def calculate_return(target_close: Any, entry_open: Any) -> float | None:
    close = number(target_close)
    entry = number(entry_open)
    if close is None or entry is None or entry <= 0:
        return None
    return rounded((close / entry - 1) * 100)


def calculate_mfe_mae(
    bars: list[dict[str, Any]],
    entry_open: Any,
) -> tuple[float | None, float | None, float | None, float | None]:
    entry = number(entry_open)
    highs = [number(bar.get("high")) for bar in bars]
    lows = [number(bar.get("low")) for bar in bars]
    if (
        entry is None
        or entry <= 0
        or not bars
        or any(value is None for value in highs)
        or any(value is None for value in lows)
    ):
        return None, None, None, None
    highest = max(value for value in highs if value is not None)
    lowest = min(value for value in lows if value is not None)
    return (
        calculate_return(highest, entry),
        calculate_return(lowest, entry),
        rounded(highest),
        rounded(lowest),
    )


def calculate_max_drawdown(bars: list[dict[str, Any]], entry_open: Any) -> float | None:
    """Calculate peak-to-subsequent-low drawdown from daily OHLC.

    A day's low is compared with peaks known before that day's high is added.
    This avoids inventing an intraday high-before-low ordering that daily bars
    cannot prove.
    """
    peak = number(entry_open)
    if peak is None or peak <= 0 or not bars:
        return None
    worst = 0.0
    for bar in bars:
        low = number(bar.get("low"))
        high = number(bar.get("high"))
        if low is None or high is None or low <= 0 or high <= 0:
            return None
        worst = min(worst, (low / peak - 1) * 100)
        peak = max(peak, high)
    return rounded(worst)


def sample_label(sample_count: int) -> str:
    if sample_count < MIN_OBSERVATION_SAMPLE:
        return "樣本不足"
    if sample_count < MIN_NORMAL_SAMPLE:
        return "僅供觀察"
    return "可正常比較"


def _snapshot_date(snapshot: dict[str, Any]) -> str:
    return valid_iso_date(
        snapshot.get("dataDate")
        or snapshot.get("latest_trade_date")
        or snapshot.get("latestTradeDate")
        or snapshot.get("date")
    )


def _snapshot_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = snapshot.get("items")
    return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _calendar(cache: dict[str, Any], snapshots: list[dict[str, Any]]) -> list[str]:
    values: set[str] = set()
    for value in cache.get("calendar", []) if isinstance(cache.get("calendar"), list) else []:
        if valid_iso_date(value):
            values.add(valid_iso_date(value))
    benchmark = cache.get("benchmark")
    if isinstance(benchmark, list):
        values.update(valid_iso_date(row.get("date")) for row in benchmark if isinstance(row, dict))
    stocks = cache.get("stocks")
    if isinstance(stocks, dict):
        for stock in stocks.values():
            bars = stock.get("bars") if isinstance(stock, dict) else []
            if isinstance(bars, list):
                values.update(valid_iso_date(row.get("date")) for row in bars if isinstance(row, dict))
    values.update(_snapshot_date(snapshot) for snapshot in snapshots)
    return sorted(value for value in values if value)


def _stock_bars(
    cache: dict[str, Any],
    code: str,
    market: str = "",
) -> dict[str, dict[str, Any]]:
    stocks = cache.get("stocks") if isinstance(cache.get("stocks"), dict) else {}
    stock = stocks.get(str(code)) if isinstance(stocks, dict) else None
    normalized_market = market_key(market)
    bars_by_market = (
        stock.get("barsByMarket")
        if isinstance(stock, dict) and isinstance(stock.get("barsByMarket"), dict)
        else {}
    )
    if (
        normalized_market
        and isinstance(bars_by_market.get(normalized_market), list)
    ):
        bars = bars_by_market[normalized_market]
    else:
        bars = stock.get("bars") if isinstance(stock, dict) else []
    return {
        valid_iso_date(row.get("date")): dict(row)
        for row in bars or []
        if isinstance(row, dict)
        and valid_iso_date(row.get("date"))
        and (
            not normalized_market
            or not market_key(row.get("market"))
            or market_key(row.get("market")) == normalized_market
        )
    }


def _benchmark_bars(cache: dict[str, Any]) -> dict[str, dict[str, Any]]:
    bars = cache.get("benchmark") if isinstance(cache.get("benchmark"), list) else []
    return {
        valid_iso_date(row.get("date")): dict(row)
        for row in bars
        if isinstance(row, dict) and valid_iso_date(row.get("date"))
    }


def _coverage_ok(cache: dict[str, Any], market: str, trade_date: str) -> bool:
    coverage = cache.get("coverage") if isinstance(cache.get("coverage"), dict) else {}
    market_rows = coverage.get(market) if isinstance(coverage.get(market), dict) else {}
    row = market_rows.get(trade_date)
    return bool(row.get("ok")) if isinstance(row, dict) else False


def _bar_has_trade(bar: dict[str, Any]) -> bool:
    if bar.get("rawPresent") is False:
        return False
    if isinstance(bar.get("hasTrade"), bool):
        return bool(bar["hasTrade"])
    volume = number(bar.get("volume"))
    transactions = number(bar.get("transactions"))
    close = number(bar.get("close"))
    if close is None or close <= 0:
        return False
    if volume is not None:
        return volume > 0
    if transactions is not None:
        return transactions > 0
    return False


def _eligible_rows(
    signal_date: str,
    code: str,
    market: str,
    cache: dict[str, Any],
    calendar: list[str],
) -> tuple[list[dict[str, Any]], str, str, int]:
    """Return valid individual-stock rows until the first unknown data gap."""
    bars = _stock_bars(cache, code, market)
    eligible: list[dict[str, Any]] = []
    barrier = ""
    entry_error = ""
    explicit_non_trade = 0
    for trade_date in (value for value in calendar if value > signal_date):
        bar = bars.get(trade_date)
        if bar is None:
            if _coverage_ok(cache, market, trade_date):
                # A successful full-market response without this code is an
                # explicit no-quote day, not a price to carry forward.
                explicit_non_trade += 1
                continue
            barrier = trade_date
            break
        if not _bar_has_trade(bar):
            explicit_non_trade += 1
            continue
        if number(bar.get("close")) is None:
            barrier = trade_date
            break
        if not eligible and number(bar.get("open")) is None:
            entry_error = trade_date
            break
        eligible.append({**bar, "date": trade_date})
    return eligible, barrier, entry_error, explicit_non_trade


def _event_base(
    item: dict[str, Any],
    signal_date: str,
    snapshot: dict[str, Any],
    *,
    daily: bool = False,
) -> dict[str, Any]:
    code = str(item.get("code") or item.get("symbol") or "").strip()
    version = str(item.get("scoreVersion") or snapshot.get("scoreVersion") or "unknown").strip()
    prefix = "daily_" if daily else ""
    signal_id = f"{prefix}{code}_{signal_date}_{version}"
    return {
        "signalId": signal_id,
        "signalMode": "daily_observation" if daily else "first_entry",
        "signalDate": signal_date,
        "code": code,
        "name": item.get("name") or "",
        "market": item.get("market") or "",
        "industry": item.get("industry") or "",
        "concepts": list(item.get("concepts") or []),
        "scoreVersion": version,
        "signalRank": integer(item.get("rank")),
        "signalScore": number(item.get("totalScore")),
        "fundamentalScore": number(item.get("fundamentalScore")),
        "technicalScore": number(item.get("technicalScore")),
        "chipScore": number(item.get("chipScore")),
        "turnoverScore": number(item.get("turnoverScore")),
        "signalClose": number(item.get("close")),
        "changePercent": number(item.get("changePercent")),
        "tradeType": item.get("tradeType") or "",
        "riskLabel": item.get("riskLabel") or "",
        "entryStatus": item.get("entryStatus") or "新進榜",
        "firstSeenDate": signal_date,
        "lastSeenDate": signal_date,
        "consecutiveDays": max(integer(item.get("consecutiveDays")) or 1, 1),
        "appearances5d": max(integer(item.get("appearances5d")) or 1, 1),
        "appearances20d": max(integer(item.get("appearances20d")) or 1, 1),
        "periodHighestRank": integer(item.get("rank")),
        "periodHighestScore": number(item.get("totalScore")),
        "droppedOut": False,
        "reentered": False,
        "signalCycleNumber": 1,
        "statusLabels": list(item.get("statusLabels") or []),
        "_observations": [
            {
                "date": signal_date,
                "rank": integer(item.get("rank")),
                "score": number(item.get("totalScore")),
                "item": dict(item),
            }
        ],
    }


def _period_date_for_event(
    event: dict[str, Any],
    cache: dict[str, Any],
    calendar: list[str],
    period: int,
) -> str:
    rows, _, _, _ = _eligible_rows(
        event["signalDate"],
        event["code"],
        market_key(event.get("market")),
        cache,
        calendar,
    )
    return rows[period - 1]["date"] if len(rows) >= period else ""


def build_signal_cycles(
    snapshots: list[dict[str, Any]],
    cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Build non-overlapping first-entry cycles and separate daily signals."""
    snapshots = sorted(
        (snapshot for snapshot in snapshots if _snapshot_date(snapshot)),
        key=_snapshot_date,
    )
    calendar = _calendar(cache, snapshots)
    index_by_date = {value: index for index, value in enumerate(calendar)}
    snapshot_codes_by_date = {
        _snapshot_date(snapshot): {
            str(item.get("code") or item.get("symbol") or "").strip()
            for item in _snapshot_items(snapshot)
        }
        for snapshot in snapshots
    }
    snapshot_dates = sorted(snapshot_codes_by_date)

    def confirmed_absence_gap(code: str, left_date: str, right_date: str) -> int:
        return sum(
            code not in snapshot_codes_by_date[trade_date]
            for trade_date in snapshot_dates
            if left_date < trade_date < right_date
        )

    events: list[dict[str, Any]] = []
    daily_signals: list[dict[str, Any]] = []
    latest_by_code: dict[str, dict[str, Any]] = {}
    latest_daily_by_code: dict[str, dict[str, Any]] = {}
    seen_dates_by_code: defaultdict[str, list[str]] = defaultdict(list)
    cycle_count: defaultdict[str, int] = defaultdict(int)

    for snapshot in snapshots:
        signal_date = _snapshot_date(snapshot)
        for item in _snapshot_items(snapshot):
            code = str(item.get("code") or item.get("symbol") or "").strip()
            if not code:
                continue
            prior_daily = latest_daily_by_code.get(code)
            right = index_by_date.get(signal_date)
            prior_daily_date = (
                str(prior_daily.get("signalDate") or "")
                if prior_daily
                else ""
            )
            left = index_by_date.get(prior_daily_date)
            adjacent_complete_snapshot = bool(
                prior_daily
                and left is not None
                and right is not None
                and right == left + 1
            )
            daily_gap = (
                confirmed_absence_gap(
                    code,
                    prior_daily_date,
                    signal_date,
                )
                if prior_daily
                else 0
            )
            daily_event = _event_base(item, signal_date, snapshot, daily=True)
            daily_event["reentered"] = bool(prior_daily and daily_gap > 0)
            daily_event["entryStatus"] = (
                "新進榜"
                if prior_daily is None
                else "重返榜"
                if daily_gap > 0
                else "連續入榜"
                if adjacent_complete_snapshot
                else "快照缺口待確認"
            )
            previous_rank = integer(prior_daily.get("signalRank")) if prior_daily else None
            current_rank = integer(item.get("rank"))
            rank_change = (
                previous_rank - current_rank
                if previous_rank is not None and current_rank is not None
                else None
            )
            daily_event["previousRank"] = previous_rank
            daily_event["rankChange"] = rank_change
            daily_event["rankTrend"] = (
                "排名上升"
                if rank_change is not None and rank_change > 0
                else "排名下降"
                if rank_change is not None and rank_change < 0
                else "排名持平"
                if rank_change == 0
                else "資料不足"
            )
            previous_score = number(prior_daily.get("signalScore")) if prior_daily else None
            current_score = number(item.get("totalScore"))
            daily_event["scoreTrend"] = (
                "分數上升"
                if previous_score is not None and current_score is not None and current_score > previous_score
                else "分數下降"
                if previous_score is not None and current_score is not None and current_score < previous_score
                else "分數持平"
                if previous_score is not None and current_score is not None
                else "資料不足"
            )
            daily_event["consecutiveDays"] = (
                (integer(prior_daily.get("consecutiveDays")) or 1) + 1
                if adjacent_complete_snapshot
                else 1
            )
            seen_dates_by_code[code].append(signal_date)
            if right is not None:
                window5 = set(calendar[max(0, right - 4) : right + 1])
                window20 = set(calendar[max(0, right - 19) : right + 1])
                daily_event["appearances5d"] = sum(
                    value in window5 for value in seen_dates_by_code[code]
                )
                daily_event["appearances20d"] = sum(
                    value in window20 for value in seen_dates_by_code[code]
                )
            daily_event["signalTypes"] = _signal_types(daily_event)
            daily_signals.append(daily_event)
            latest_daily_by_code[code] = daily_event

            prior = latest_by_code.get(code)
            version = str(item.get("scoreVersion") or snapshot.get("scoreVersion") or "unknown")
            new_cycle = prior is None
            gap_days = 0
            cycle_reason = "initial"
            if prior is not None:
                gap_days = confirmed_absence_gap(
                    code,
                    str(prior.get("lastSeenDate") or ""),
                    signal_date,
                )
                d20_date = _period_date_for_event(prior, cache, calendar, MAX_HOLDING_DAYS)
                if gap_days >= NEW_SIGNAL_AFTER_TRADING_DAYS:
                    new_cycle = True
                    cycle_reason = "gap"
                elif d20_date and signal_date > d20_date:
                    new_cycle = True
                    cycle_reason = "d20"
                else:
                    new_cycle = False
                    cycle_reason = "continue"

            if new_cycle:
                if prior is not None:
                    prior["_closedReason"] = cycle_reason
                    prior["_nextSeenDate"] = signal_date
                event = _event_base(item, signal_date, snapshot)
                cycle_count[code] += 1
                event["signalCycleNumber"] = cycle_count[code]
                event["reentered"] = cycle_reason in {"gap", "d20"}
                event["entryStatus"] = (
                    "重返榜"
                    if cycle_reason == "gap"
                    else "D+20 後新週期"
                    if cycle_reason == "d20"
                    else "新進榜"
                )
                event["appearances5d"] = daily_event["appearances5d"]
                event["appearances20d"] = daily_event["appearances20d"]
                event["consecutiveDays"] = daily_event["consecutiveDays"]
                event["previousRank"] = daily_event["previousRank"]
                event["rankChange"] = daily_event["rankChange"]
                event["rankTrend"] = daily_event["rankTrend"]
                event["scoreTrend"] = daily_event["scoreTrend"]
                event["entryRankTrend"] = daily_event["rankTrend"]
                event["entryScoreTrend"] = daily_event["scoreTrend"]
                event["entrySignalTypes"] = _signal_types(event)
                # ``signalTypes`` is the as-of-entry classification used by
                # formal first-entry statistics. It must never absorb future
                # persistence, dropout, or rank/score movement.
                event["signalTypes"] = list(event["entrySignalTypes"])
                event["_closedReason"] = ""
                event["_hadGap"] = False
                events.append(event)
                latest_by_code[code] = event
                continue

            event = prior
            assert event is not None
            event["_observations"].append(
                {
                    "date": signal_date,
                    "rank": integer(item.get("rank")),
                    "score": number(item.get("totalScore")),
                    "item": dict(item),
                }
            )
            event["lastSeenDate"] = signal_date
            event["periodHighestRank"] = min(
                value
                for value in (event.get("periodHighestRank"), integer(item.get("rank")))
                if value is not None
            )
            scores = [event.get("periodHighestScore"), number(item.get("totalScore"))]
            event["periodHighestScore"] = max(value for value in scores if value is not None)
            event["appearances5d"] = daily_event["appearances5d"]
            event["appearances20d"] = daily_event["appearances20d"]
            if gap_days:
                event["reentered"] = True
                event["_hadGap"] = True

    latest_snapshot_date = max((_snapshot_date(snapshot) for snapshot in snapshots), default="")
    for event in events:
        observations = sorted(event["_observations"], key=lambda row: row["date"])
        current_streak = 0
        max_streak = 0
        previous_date = ""
        for observation in observations:
            current_date = observation["date"]
            if previous_date:
                left = index_by_date.get(previous_date)
                right = index_by_date.get(current_date)
                adjacent = left is not None and right == left + 1
                current_streak = current_streak + 1 if adjacent else 1
            else:
                current_streak = 1
            max_streak = max(max_streak, current_streak)
            previous_date = current_date
        event["consecutiveDays"] = max_streak
        event["droppedOut"] = (
            bool(event.get("_hadGap"))
            or event.get("_closedReason") == "gap"
            or bool(
                not event.get("_closedReason")
                and latest_snapshot_date
                and event["lastSeenDate"] < latest_snapshot_date
            )
        )
        ranks = [row["rank"] for row in observations if row.get("rank") is not None]
        if len(ranks) >= 2:
            event["rankTrend"] = "排名上升" if ranks[-1] < ranks[-2] else "排名下降" if ranks[-1] > ranks[-2] else "排名持平"
        else:
            event["rankTrend"] = "資料不足"
        scores = [row["score"] for row in observations if row.get("score") is not None]
        if len(scores) >= 2:
            event["scoreTrend"] = "分數上升" if scores[-1] > scores[-2] else "分數下降" if scores[-1] < scores[-2] else "分數持平"
        else:
            event["scoreTrend"] = "資料不足"
        event["trackingSignalTypes"] = _signal_types(event)
        event["signalTypes"] = list(event.get("entrySignalTypes") or [])
    return events, daily_signals, calendar


def _signal_types(event: dict[str, Any]) -> list[str]:
    entry_status = str(event.get("entryStatus") or "")
    labels = [
        "重返榜"
        if event.get("reentered")
        else "快照缺口待確認"
        if entry_status == "快照缺口待確認"
        else "連續入榜"
        if entry_status == "連續入榜"
        else "新進榜"
    ]
    consecutive = integer(event.get("consecutiveDays")) or 1
    if consecutive == 2:
        labels.append("連續入榜 2 日")
    elif consecutive >= 3:
        labels.append("連續入榜 3 日以上")
    if event.get("rankTrend") in {"排名上升", "排名下降"}:
        labels.append(str(event["rankTrend"]))
    if (integer(event.get("appearances20d")) or 0) >= 10:
        labels.append("月度常駐")
    status_labels = {str(value) for value in event.get("statusLabels") or []}
    if "單日爆發" in status_labels or (
        (integer(event.get("appearances5d")) or 0) == 1
        and (number(event.get("changePercent")) or 0) >= 9
    ):
        labels.append("單日爆發")
    return list(dict.fromkeys(labels))


def _benchmark_metrics(
    event: dict[str, Any],
    target_rows: dict[int, dict[str, Any]],
    cache: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    benchmark = _benchmark_bars(cache)
    output: dict[str, Any] = {
        "benchmarkCode": BENCHMARK_CODE,
        "benchmarkName": BENCHMARK_NAME,
        "benchmarkEntry": None,
        "benchmarkStatus": "pending",
    }
    flags: list[str] = []
    entry_date = event.get("entryTradeDate")
    entry_bar = benchmark.get(entry_date) if entry_date else None
    entry = number(entry_bar.get("open")) if isinstance(entry_bar, dict) else None
    output["benchmarkEntry"] = rounded(entry)
    if entry_date and entry is None:
        flags.append("benchmark_unavailable")
    completed_benchmark_periods = 0
    for period in PERIODS:
        target = target_rows.get(period)
        field = f"benchmarkD{period}Return"
        date_field = f"benchmarkD{period}TradeDate"
        output[field] = None
        output[date_field] = target.get("date") if target else None
        if not target:
            continue
        bar = benchmark.get(str(target.get("date")))
        value = calculate_return(bar.get("close"), entry) if isinstance(bar, dict) else None
        output[field] = value
        if value is None:
            flags.append("benchmark_unavailable")
        else:
            completed_benchmark_periods += 1
    if not entry_date:
        output["benchmarkStatus"] = "pending"
    elif flags:
        output["benchmarkStatus"] = "benchmark_unavailable"
    elif completed_benchmark_periods:
        output["benchmarkStatus"] = "ok"
    else:
        output["benchmarkStatus"] = "tracking"
    return output, list(dict.fromkeys(flags))


def evaluate_signal(
    event: dict[str, Any],
    cache: dict[str, Any],
    calendar: list[str],
    generated_at: str,
) -> dict[str, Any]:
    output = {key: value for key, value in event.items() if not key.startswith("_")}
    market = market_key(output.get("market"))
    rows, barrier, entry_error, explicit_non_trade = _eligible_rows(
        output["signalDate"], output["code"], market, cache, calendar
    )
    future_calendar = [value for value in calendar if value > output["signalDate"]]
    errors: list[str] = []
    status_flags: list[str] = []

    output.update(
        {
            "entryTradeDate": None,
            "entryOpen": None,
            "entryClose": None,
            "entryPriceSource": None,
            "entryPriceAvailable": False,
            "completedPeriods": [],
            "pendingPeriods": [f"D+{period}" for period in PERIODS],
            "lastUpdatedAt": generated_at,
            "errorReason": "",
        }
    )
    target_rows: dict[int, dict[str, Any]] = {}
    for period in PERIODS:
        key = f"d{period}"
        output[f"{key}TradeDate"] = None
        output[f"{key}Close"] = None
        output[f"{key}Return"] = None
        output[f"mfe{period}"] = None
        output[f"mae{period}"] = None
        output[f"excessReturnD{period}"] = None
        output[f"outperformedBenchmarkD{period}"] = None

    if not rows:
        if entry_error:
            progress_status = "entry_price_unavailable"
            status_flags.append(progress_status)
            errors.append(f"official opening price unavailable on {entry_error}")
        elif barrier:
            progress_status = "price_data_incomplete"
            status_flags.append(progress_status)
            errors.append(f"official stock-price coverage unavailable from {barrier}")
        elif future_calendar and explicit_non_trade:
            progress_status = "suspended"
            status_flags.append(progress_status)
            errors.append("no valid individual-stock trade after signal")
        elif future_calendar:
            progress_status = "price_data_incomplete"
            status_flags.append(progress_status)
            errors.append("stock is absent from successful official market responses")
        else:
            progress_status = "waiting_entry"
    else:
        entry = rows[0]
        output.update(
            {
                "entryTradeDate": entry["date"],
                "entryOpen": rounded(number(entry.get("open"))),
                "entryClose": rounded(number(entry.get("close"))),
                "entryPriceSource": entry.get("source") or "official TWSE/TPEx daily quotes",
                "entryPriceAvailable": True,
            }
        )
        completed: list[str] = []
        for period in PERIODS:
            if len(rows) < period:
                continue
            target = rows[period - 1]
            target_rows[period] = target
            key = f"d{period}"
            output[f"{key}TradeDate"] = target["date"]
            output[f"{key}Close"] = rounded(number(target.get("close")))
            output[f"{key}Return"] = calculate_return(target.get("close"), entry.get("open"))
            completed.append(f"D+{period}")
            mfe, mae, _, _ = calculate_mfe_mae(rows[:period], entry.get("open"))
            output[f"mfe{period}"] = mfe
            output[f"mae{period}"] = mae
            if mfe is None or mae is None:
                status_flags.append("price_data_incomplete")
        output["completedPeriods"] = completed
        output["pendingPeriods"] = [
            f"D+{period}" for period in PERIODS if f"D+{period}" not in completed
        ]
        if len(rows) >= 20:
            mfe20, mae20, highest20, lowest20 = calculate_mfe_mae(rows[:20], entry.get("open"))
            output["mfe20"] = mfe20
            output["mae20"] = mae20
            output["highestPrice20"] = highest20
            output["lowestPrice20"] = lowest20
            output["highestReturn20"] = calculate_return(highest20, entry.get("open"))
            output["lowestReturn20"] = calculate_return(lowest20, entry.get("open"))
            output["maxDrawdown20"] = calculate_max_drawdown(rows[:20], entry.get("open"))
        else:
            output.update(
                {
                    "highestPrice20": None,
                    "lowestPrice20": None,
                    "highestReturn20": None,
                    "lowestReturn20": None,
                    "maxDrawdown20": None,
                }
            )
        if barrier:
            status_flags.append("price_data_incomplete")
            errors.append(f"official stock-price coverage unavailable from {barrier}")
        if output.get("d20Return") is not None:
            progress_status = "completed"
        elif any(output.get(f"d{period}Return") is not None for period in (3, 5, 10)):
            progress_status = "partially_completed"
        elif output.get("d1Return") is not None:
            progress_status = "tracking"
        else:
            progress_status = "entry_ready"

    benchmark, benchmark_flags = _benchmark_metrics(output, target_rows, cache)
    output.update(benchmark)
    status_flags.extend(benchmark_flags)
    for period in PERIODS:
        stock_return = output.get(f"d{period}Return")
        benchmark_return = output.get(f"benchmarkD{period}Return")
        if stock_return is None or benchmark_return is None:
            continue
        excess = rounded(stock_return - benchmark_return)
        output[f"excessReturnD{period}"] = excess
        output[f"outperformedBenchmarkD{period}"] = excess > 0

    output["trackingStatus"] = progress_status
    output["statusFlags"] = list(dict.fromkeys(status_flags))
    if progress_status in {
        "entry_price_unavailable",
        "price_data_incomplete",
        "suspended",
        "delisted",
        "error",
    }:
        validation_status = progress_status
    elif "price_data_incomplete" in output["statusFlags"]:
        validation_status = "price_data_incomplete"
    elif "benchmark_unavailable" in output["statusFlags"]:
        validation_status = "benchmark_unavailable"
    else:
        validation_status = progress_status
    output["validationStatus"] = validation_status
    output["absoluteSuccessD5"] = (
        output.get("d5Return") > ABSOLUTE_SUCCESS_THRESHOLD
        if output.get("d5Return") is not None
        else None
    )
    output["absoluteSuccessD20"] = (
        output.get("d20Return") > ABSOLUTE_SUCCESS_THRESHOLD
        if output.get("d20Return") is not None
        else None
    )
    output["riskAdjustedSuccessD20"] = (
        output.get("d20Return") > ABSOLUTE_SUCCESS_THRESHOLD
        and output.get("mae20") is not None
        and output["mae20"] >= MAX_ACCEPTABLE_MAE_20
        if output.get("d20Return") is not None
        else None
    )
    output["errorReason"] = "; ".join(dict.fromkeys(errors))
    return output


def assert_immutable_signals(
    existing_items: list[dict[str, Any]],
    current_items: list[dict[str, Any]],
) -> None:
    existing = {
        str(item.get("signalId")): item
        for item in existing_items
        if isinstance(item, dict) and item.get("signalId")
    }
    current_ids = {
        str(item.get("signalId"))
        for item in current_items
        if isinstance(item, dict) and item.get("signalId")
    }
    missing_ids = sorted(set(existing) - current_ids)
    if missing_ids:
        raise ValueError(
            "immutable historical signals disappeared from rebuild: "
            + ", ".join(missing_ids)
        )
    for item in current_items:
        prior = existing.get(str(item.get("signalId")))
        if not prior:
            continue
        changed = [
            field
            for field in IMMUTABLE_SIGNAL_FIELDS
            if prior.get(field) != item.get(field)
        ]
        if changed:
            raise ValueError(
                f"immutable signal {item.get('signalId')} changed fields: {', '.join(changed)}"
            )


def _mean(values: Iterable[Any]) -> float | None:
    parsed = [number(value) for value in values]
    clean = [value for value in parsed if value is not None]
    return rounded(statistics.fmean(clean)) if clean else None


def _median(values: Iterable[Any]) -> float | None:
    parsed = [number(value) for value in values]
    clean = [value for value in parsed if value is not None]
    return rounded(statistics.median(clean)) if clean else None


def _rate(values: Iterable[Any]) -> float | None:
    clean = [value for value in values if isinstance(value, bool)]
    return rounded(sum(1 for value in clean if value) / len(clean) * 100) if clean else None


def period_statistics(events: list[dict[str, Any]], period: int) -> dict[str, Any]:
    returns = [event.get(f"d{period}Return") for event in events]
    completed = [value for value in returns if number(value) is not None]
    excess = [event.get(f"excessReturnD{period}") for event in events]
    return {
        "period": f"D+{period}",
        "completedSamples": len(completed),
        "averageReturn": _mean(completed),
        "medianReturn": _median(completed),
        "winRate": _rate([number(value) > ABSOLUTE_SUCCESS_THRESHOLD for value in completed]),
        "averageExcessReturn": _mean(excess),
        "benchmarkWinRate": _rate(
            [event.get(f"outperformedBenchmarkD{period}") for event in events]
        ),
        "averageMfe": _mean(event.get(f"mfe{period}") for event in events),
        "averageMae": _mean(event.get(f"mae{period}") for event in events),
    }


def _best_worst(events: list[dict[str, Any]], best: bool) -> dict[str, Any] | None:
    for period in (20, 5, 1):
        rows = [
            event
            for event in events
            if number(event.get(f"d{period}Return")) is not None
        ]
        if rows:
            selected = (max if best else min)(
                rows,
                key=lambda event: number(event.get(f"d{period}Return")) or 0,
            )
            return {
                "signalId": selected.get("signalId"),
                "code": selected.get("code"),
                "name": selected.get("name"),
                "period": f"D+{period}",
                "return": selected.get(f"d{period}Return"),
            }
    return None


def summary_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_statuses = {
        "entry_price_unavailable",
        "price_data_incomplete",
        "suspended",
        "delisted",
        "error",
    }
    tracking = [
        event for event in events if event.get("trackingStatus") != "completed"
    ]
    periods = {period: period_statistics(events, period) for period in PERIODS}
    d20_drawdowns = [event.get("maxDrawdown20") for event in events]
    return {
        "totalSignals": len(events),
        "completedSignals": sum(event.get("trackingStatus") == "completed" for event in events),
        "trackingSignals": len(tracking),
        "invalidSignals": sum(event.get("validationStatus") in invalid_statuses for event in events),
        "averageD1Return": periods[1]["averageReturn"],
        "medianD1Return": periods[1]["medianReturn"],
        "averageD5Return": periods[5]["averageReturn"],
        "medianD5Return": periods[5]["medianReturn"],
        "averageD20Return": periods[20]["averageReturn"],
        "medianD20Return": periods[20]["medianReturn"],
        "winRateD1": periods[1]["winRate"],
        "winRateD5": periods[5]["winRate"],
        "winRateD20": periods[20]["winRate"],
        "benchmarkWinRateD5": periods[5]["benchmarkWinRate"],
        "benchmarkWinRateD20": periods[20]["benchmarkWinRate"],
        "averageExcessReturnD5": periods[5]["averageExcessReturn"],
        "averageExcessReturnD20": periods[20]["averageExcessReturn"],
        "averageMfe20": _mean(event.get("mfe20") for event in events),
        "averageMae20": _mean(event.get("mae20") for event in events),
        "worstDrawdown": min(
            (value for value in (number(item) for item in d20_drawdowns) if value is not None),
            default=None,
        ),
        "bestSignal": _best_worst(events, True),
        "worstSignal": _best_worst(events, False),
    }


def build_summary(
    events: list[dict[str, Any]],
    signal_dates: list[str],
    generated_at: str,
) -> dict[str, Any]:
    unique_dates = sorted(set(value for value in signal_dates if valid_iso_date(value)))
    recent5_dates = set(unique_dates[-5:])
    recent20_dates = set(unique_dates[-20:])
    recent5 = [event for event in events if event.get("signalDate") in recent5_dates]
    recent20 = [event for event in events if event.get("signalDate") in recent20_dates]
    months: dict[str, Any] = {}
    for month in sorted({str(event.get("signalDate", ""))[:7] for event in events if event.get("signalDate")}):
        months[month] = summary_metrics(
            [event for event in events if str(event.get("signalDate", "")).startswith(month)]
        )
    all_metrics = summary_metrics(events)
    return {
        "status": "ok",
        "ok": True,
        "validationVersion": VALIDATION_VERSION,
        "eventMode": "first_entry",
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latestSignalDate": max(unique_dates, default=""),
        "latest_trade_date": max(unique_dates, default=""),
        **all_metrics,
        "all": all_metrics,
        "recent5": summary_metrics(recent5),
        "recent20": summary_metrics(recent20),
        "monthly": months,
        "periods": [period_statistics(events, period) for period in PERIODS],
        "denominatorRule": "Only signals with a completed period are included in that period's rate.",
    }


def _group_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    d5 = period_statistics(events, 5)
    d20 = period_statistics(events, 20)
    benchmark_d5 = [
        event.get("outperformedBenchmarkD5")
        for event in events
    ]
    benchmark_d20 = [
        event.get("outperformedBenchmarkD20")
        for event in events
    ]
    return {
        "sampleCount": len(events),
        "completedD5": d5["completedSamples"],
        "averageD5Return": d5["averageReturn"],
        "medianD5Return": d5["medianReturn"],
        "winRateD5": d5["winRate"],
        "completedD20": d20["completedSamples"],
        "averageD20Return": d20["averageReturn"],
        "medianD20Return": d20["medianReturn"],
        "winRateD20": d20["winRate"],
        "averageMae20": _mean(event.get("mae20") for event in events),
        "benchmarkOutperformanceRate": _rate(benchmark_d5),
        "benchmarkOutperformanceHorizon": "D+5",
        "benchmarkOutperformanceRateD5": _rate(benchmark_d5),
        "benchmarkOutperformanceRateD20": _rate(benchmark_d20),
        "sampleLabel": sample_label(max(d5["completedSamples"], d20["completedSamples"])),
        "sampleLabelD5": sample_label(d5["completedSamples"]),
        "sampleLabelD20": sample_label(d20["completedSamples"]),
    }


def _factor_band(value: Any) -> str:
    score = number(value)
    if score is None:
        return "資料不足"
    if score >= FACTOR_HIGH_THRESHOLD:
        return "高分"
    if score >= FACTOR_MEDIUM_THRESHOLD:
        return "中分"
    return "低分"


def _single_value_groups(
    events: list[dict[str, Any]],
    field: str,
    dimension: str,
) -> list[dict[str, Any]]:
    values = sorted({str(event.get(field) or "未分類") for event in events})
    return [
        {
            "dimension": dimension,
            "label": value,
            **_group_metrics([event for event in events if str(event.get(field) or "未分類") == value]),
        }
        for value in values
    ]


def _multi_value_groups(
    events: list[dict[str, Any]],
    field: str,
    dimension: str,
) -> list[dict[str, Any]]:
    values = sorted(
        {
            str(value)
            for event in events
            for value in event.get(field) or []
            if str(value).strip()
        }
    )
    return [
        {
            "dimension": dimension,
            "label": value,
            **_group_metrics([event for event in events if value in (event.get(field) or [])]),
        }
        for value in values
    ]


def _factor_groups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = (
        ("fundamentalScore", "基本面"),
        ("technicalScore", "技術面"),
        ("chipScore", "籌碼面"),
        ("turnoverScore", "週轉熱度"),
    )
    rows: list[dict[str, Any]] = []
    for field, label in definitions:
        for band in ("高分", "中分", "低分", "資料不足"):
            subset = [event for event in events if _factor_band(event.get(field)) == band]
            rows.append(
                {
                    "dimension": "factor",
                    "factor": field,
                    "factorLabel": label,
                    "band": band,
                    "label": f"{label}{band}",
                    **_group_metrics(subset),
                }
            )
    return rows


def _factor_mode(
    events: list[dict[str, Any]],
    mode: str,
    insight_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    groups = {
        "factors": _factor_groups(events),
        "signalTypes": _multi_value_groups(events, "signalTypes", "signal_type"),
        "tradeTypes": _single_value_groups(events, "tradeType", "trade_type"),
        "riskLabels": _single_value_groups(events, "riskLabel", "risk_label"),
        "scoreVersions": _single_value_groups(events, "scoreVersion", "score_version"),
    }
    insight_events = events if insight_events is None else insight_events
    insight_factor_groups = _factor_groups(insight_events)
    high_groups = [
        row
        for row in insight_factor_groups
        if row["band"] == "高分" and row["completedD5"] > 0
    ]
    sufficiently_sampled = [
        row for row in high_groups if row["completedD5"] >= MIN_OBSERVATION_SAMPLE
    ]
    strongest = max(
        sufficiently_sampled,
        key=lambda row: row["winRateD5"] if row["winRateD5"] is not None else -1,
        default=None,
    )
    weakest = min(
        sufficiently_sampled,
        key=lambda row: row["winRateD5"] if row["winRateD5"] is not None else 101,
        default=None,
    )
    warning = ""
    if not sufficiently_sampled:
        warning = "高分因子完成樣本少於 10，暫不判定近期最強或最弱因子。"
    return {
        "mode": mode,
        "itemsCount": len(events),
        "groups": groups,
        "insights": {
            "strongestFactor": strongest,
            "weakestFactor": weakest,
            "warning": warning,
            "window": "最近 20 個有榜單的交易日",
            "signalDateCount": len(
                {
                    str(event.get("signalDate") or "")
                    for event in insight_events
                    if event.get("signalDate")
                }
            ),
        },
    }


def _recent_signal_events(
    events: list[dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    dates = sorted(
        {
            str(event.get("signalDate") or "")
            for event in events
            if event.get("signalDate")
        }
    )[-limit:]
    selected = set(dates)
    return [
        event
        for event in events
        if str(event.get("signalDate") or "") in selected
    ]


def _versioned_factor_mode(events: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """Keep factor/type/risk comparisons inside one score version."""
    versions = sorted({str(event.get("scoreVersion") or "unknown") for event in events})
    if not versions:
        primary = _factor_mode([], mode)
        primary["selectedScoreVersion"] = None
        primary["availableScoreVersions"] = []
        primary["byScoreVersion"] = {}
        return primary
    latest_event = max(
        events,
        key=lambda event: (
            str(event.get("signalDate") or ""),
            str(event.get("scoreVersion") or ""),
        ),
    )
    selected = str(latest_event.get("scoreVersion") or "unknown")
    by_version: dict[str, dict[str, Any]] = {}
    for version in versions:
        version_events = [
            event
            for event in events
            if str(event.get("scoreVersion") or "unknown") == version
        ]
        by_version[version] = _factor_mode(
            version_events,
            mode,
            _recent_signal_events(version_events),
        )
    primary = dict(by_version[selected])
    # This selector is the only cross-version view; every performance group and
    # insight above remains scoped to ``selectedScoreVersion``.
    primary["groups"] = dict(primary["groups"])
    primary["groups"]["scoreVersions"] = _single_value_groups(
        events,
        "scoreVersion",
        "score_version",
    )
    primary["selectedScoreVersion"] = selected
    primary["availableScoreVersions"] = versions
    primary["totalItemsCount"] = len(events)
    primary["byScoreVersion"] = by_version
    return primary


def build_factor_performance(
    events: list[dict[str, Any]],
    daily_events: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "ok": True,
        "validationVersion": VALIDATION_VERSION,
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latest_trade_date": max(
            (str(event.get("signalDate") or "") for event in events),
            default="",
        ),
        "thresholds": {
            "high": FACTOR_HIGH_THRESHOLD,
            "medium": FACTOR_MEDIUM_THRESHOLD,
            "insufficientSample": MIN_OBSERVATION_SAMPLE,
            "normalComparisonSample": MIN_NORMAL_SAMPLE,
        },
        "firstEntry": _versioned_factor_mode(events, "first_entry"),
        "dailyObservation": _versioned_factor_mode(daily_events, "daily_observation"),
    }


def _compound(values: Iterable[Any]) -> float | None:
    clean = [number(value) for value in values]
    parsed = [value for value in clean if value is not None]
    if not parsed:
        return None
    growth = 1.0
    for value in parsed:
        growth *= 1 + value / 100
    return rounded((growth - 1) * 100)


def _curve_drawdown(cumulative_values: list[float]) -> float | None:
    if not cumulative_values:
        return None
    peak = 1.0
    worst = 0.0
    for value in cumulative_values:
        wealth = 1 + value / 100
        peak = max(peak, wealth)
        worst = min(worst, (wealth / peak - 1) * 100)
    return rounded(worst)


def build_portfolio_curve(
    events: list[dict[str, Any]],
    cache: dict[str, Any],
    calendar: list[str],
    holding_days: int,
) -> dict[str, Any]:
    positions_by_date: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    valid_positions = 0
    incomplete_positions: dict[str, list[str]] = {}
    for event in events:
        if not event.get("entryPriceAvailable"):
            continue
        market = market_key(event.get("market"))
        rows, barrier, _, _ = _eligible_rows(
            event["signalDate"],
            event["code"],
            market,
            cache,
            calendar,
        )
        if not rows:
            continue
        usable = rows[:holding_days]
        completed = len(rows) >= holding_days
        entry_date = str(usable[0]["date"])
        end_date = (
            str(usable[-1]["date"])
            if completed
            else max((value for value in calendar if value >= entry_date), default=entry_date)
        )
        stock_bars = _stock_bars(cache, str(event["code"]), market)
        incomplete_dates: list[str] = []
        for trade_date in (
            value for value in calendar if entry_date <= value <= end_date
        ):
            bar = stock_bars.get(trade_date)
            if bar is None:
                if trade_date == barrier or _coverage_ok(cache, market, trade_date):
                    incomplete_dates.append(trade_date)
                continue
            if not _bar_has_trade(bar):
                incomplete_dates.append(trade_date)
        if barrier and barrier <= end_date and barrier not in incomplete_dates:
            incomplete_dates.append(barrier)
        if incomplete_dates:
            incomplete_positions[str(event["signalId"])] = sorted(set(incomplete_dates))
            continue

        valid_positions += 1
        theme = (
            next((str(value) for value in event.get("concepts") or [] if str(value).strip()), "")
            or str(event.get("industry") or "未分類")
        )
        previous_close: float | None = None
        for index, bar in enumerate(usable):
            close = number(bar.get("close"))
            base = number(bar.get("open")) if index == 0 else previous_close
            if close is None or base is None or base <= 0:
                break
            gross_growth = close / base
            net_growth = gross_growth
            is_entry = index == 0
            is_exit = completed and index == holding_days - 1
            if is_entry:
                net_growth *= 1 - BUY_COMMISSION_RATE
            if is_exit:
                net_growth *= 1 - SELL_COMMISSION_RATE - SELL_TRANSACTION_TAX_RATE
            positions_by_date[bar["date"]].append(
                {
                    "signalId": event["signalId"],
                    "gross": (gross_growth - 1) * 100,
                    "net": (net_growth - 1) * 100,
                    "entry": is_entry,
                    "exit": is_exit,
                    "theme": theme,
                }
            )
            previous_close = close

    calculation = {
        "calculationMode": "daily_equal_weight_active_first_entry_signals",
        "weightingRule": "Each active first-entry signal has equal weight on each invested session.",
        "rebalancingAssumption": "Daily equal weighting among active signals.",
        "costScope": "Net return includes configured entry and exit costs only; no additional intraday slippage or daily rebalancing cost is assumed.",
        "missingPriceRule": "A held position with an official no-trade or unknown-coverage session invalidates the aggregate curve; prices are never carried forward.",
    }
    if incomplete_positions:
        empty = {
            "holdingDays": holding_days,
            "status": "price_data_incomplete",
            "signalCount": valid_positions,
            "incompleteSignalCount": len(incomplete_positions),
            "incompleteSignals": [
                {"signalId": signal_id, "dates": dates}
                for signal_id, dates in sorted(incomplete_positions.items())
            ],
            "rowsCount": 0,
            "startDate": None,
            "endDate": None,
            "grossReturn": None,
            "netReturn": None,
            "benchmarkReturn": None,
            "excessReturn": None,
            "maxDrawdown": None,
            "recent5": None,
            "recent20": None,
            "benchmarkStatus": "not_calculated",
            "rows": [],
            **calculation,
        }
        empty["summary"] = {
            key: empty[key]
            for key in (
                "status",
                "signalCount",
                "rowsCount",
                "grossReturn",
                "netReturn",
                "benchmarkReturn",
                "excessReturn",
                "maxDrawdown",
                "recent5",
                "recent20",
            )
        }
        return empty

    benchmark = _benchmark_bars(cache)
    benchmark_dates = sorted(benchmark)
    benchmark_index = {value: index for index, value in enumerate(benchmark_dates)}
    rows_out: list[dict[str, Any]] = []
    gross_growth = 1.0
    net_growth = 1.0
    benchmark_growth = 1.0
    benchmark_valid = True
    benchmark_unavailable_dates: list[str] = []
    previous_invested_date = ""
    gross_curve: list[float] = []
    for trade_date in sorted(positions_by_date):
        positions = positions_by_date[trade_date]
        gross_daily = statistics.fmean(position["gross"] for position in positions)
        net_daily = statistics.fmean(position["net"] for position in positions)
        gross_growth *= 1 + gross_daily / 100
        net_growth *= 1 + net_daily / 100

        benchmark_daily: float | None = None
        benchmark_bar = benchmark.get(trade_date)
        if benchmark_valid and benchmark_bar:
            current_index = benchmark_index.get(trade_date)
            previous_index = benchmark_index.get(previous_invested_date)
            contiguous = (
                current_index is not None
                and previous_index is not None
                and current_index == previous_index + 1
            )
            previous = benchmark.get(previous_invested_date) if contiguous else None
            base = (
                number(previous.get("close"))
                if isinstance(previous, dict)
                else number(benchmark_bar.get("open"))
            )
            benchmark_daily = calculate_return(benchmark_bar.get("close"), base)
            if benchmark_daily is not None:
                benchmark_growth *= 1 + benchmark_daily / 100
            else:
                benchmark_valid = False
                benchmark_unavailable_dates.append(trade_date)
        elif benchmark_valid:
            benchmark_valid = False
            benchmark_unavailable_dates.append(trade_date)

        cumulative = rounded((gross_growth - 1) * 100) or 0.0
        cumulative_net = rounded((net_growth - 1) * 100) or 0.0
        # A missing benchmark day is explicitly null; never present it as a
        # synthetic 0% move by carrying the previous cumulative value forward.
        benchmark_cumulative = (
            rounded((benchmark_growth - 1) * 100)
            if benchmark_valid and benchmark_daily is not None
            else None
        )
        theme_counts: defaultdict[str, int] = defaultdict(int)
        for position in positions:
            theme_counts[position["theme"]] += 1
        max_theme_count = max(theme_counts.values(), default=0)
        gross_curve.append(cumulative)
        rows_out.append(
            {
                "date": trade_date,
                "grossReturn": rounded(gross_daily),
                "netReturn": rounded(net_daily),
                "cumulativeReturn": cumulative,
                "cumulativeNetReturn": cumulative_net,
                "benchmarkDailyReturn": benchmark_daily,
                "benchmarkCumulativeReturn": benchmark_cumulative,
                "excessCumulativeReturn": (
                    rounded(cumulative - benchmark_cumulative)
                    if benchmark_cumulative is not None
                    else None
                ),
                "portfolioMaxDrawdown": _curve_drawdown(gross_curve),
                "holdingCount": len(positions),
                "newEntries": sum(position["entry"] for position in positions),
                "expiredPositions": sum(position["exit"] for position in positions),
                "themeConcentration": (
                    rounded(max_theme_count / len(positions) * 100) if positions else None
                ),
                "maxThemeWeight": (
                    rounded(max_theme_count / len(positions) * 100) if positions else None
                ),
            }
        )
        previous_invested_date = trade_date

    result = {
        "holdingDays": holding_days,
        "status": "ok" if rows_out else "insufficient_data",
        "signalCount": valid_positions,
        "incompleteSignalCount": 0,
        "incompleteSignals": [],
        "rowsCount": len(rows_out),
        "startDate": rows_out[0]["date"] if rows_out else None,
        "endDate": rows_out[-1]["date"] if rows_out else None,
        "grossReturn": rows_out[-1]["cumulativeReturn"] if rows_out else None,
        "netReturn": rows_out[-1]["cumulativeNetReturn"] if rows_out else None,
        "benchmarkReturn": rows_out[-1]["benchmarkCumulativeReturn"] if rows_out else None,
        "excessReturn": rows_out[-1]["excessCumulativeReturn"] if rows_out else None,
        "maxDrawdown": _curve_drawdown(gross_curve),
        "recent5": _compound(row["grossReturn"] for row in rows_out[-5:]),
        "recent20": _compound(row["grossReturn"] for row in rows_out[-20:]),
        "benchmarkStatus": (
            "ok"
            if rows_out and not benchmark_unavailable_dates
            else "benchmark_unavailable"
            if benchmark_unavailable_dates
            else "insufficient_data"
        ),
        "benchmarkUnavailableDates": benchmark_unavailable_dates,
        "rows": rows_out,
        **calculation,
    }
    result["summary"] = {
        key: result[key]
        for key in (
            "status",
            "signalCount",
            "rowsCount",
            "grossReturn",
            "netReturn",
            "benchmarkReturn",
            "excessReturn",
            "maxDrawdown",
            "recent5",
            "recent20",
        )
    }
    return result


def build_portfolio(
    events: list[dict[str, Any]],
    cache: dict[str, Any],
    calendar: list[str],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "ok": True,
        "validationVersion": VALIDATION_VERSION,
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latest_trade_date": max(
            (str(event.get("signalDate") or "") for event in events),
            default="",
        ),
        "portfolioRule": "Each first-entry signal cycle is equally weighted and held for a fixed number of valid individual-stock trading days.",
        "calculationDisclosure": {
            "weighting": "Daily equal weight among active first-entry signals.",
            "cashHandling": "Sessions with no active signal are omitted and treated as cash.",
            "benchmarkAlignment": "The first invested session uses that session's TAIEX open; subsequent contiguous invested sessions use prior TAIEX close.",
            "missingPrices": "No stock or benchmark price is forward-filled.",
        },
        "costAssumption": {
            "buyCommissionRate": BUY_COMMISSION_RATE,
            "sellCommissionRate": SELL_COMMISSION_RATE,
            "sellTransactionTaxRate": SELL_TRANSACTION_TAX_RATE,
            "minimumCommissionIncluded": MINIMUM_COMMISSION_INCLUDED,
            "roundTripRate": rounded(
                BUY_COMMISSION_RATE + SELL_COMMISSION_RATE + SELL_TRANSACTION_TAX_RATE,
                6,
            ),
            "grossReturnIncludesCosts": False,
            "netReturnIncludesCosts": True,
        },
        "holding5": build_portfolio_curve(events, cache, calendar, 5),
        "holding20": build_portfolio_curve(events, cache, calendar, 20),
    }


def build_validation_bundle(
    snapshots: list[dict[str, Any]],
    cache: dict[str, Any],
    existing_detail: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    generated_at = generated_at or now_taipei().isoformat()
    events, daily_signals, calendar = build_signal_cycles(snapshots, cache)
    evaluated = [evaluate_signal(event, cache, calendar, generated_at) for event in events]
    evaluated_daily = [
        evaluate_signal(event, cache, calendar, generated_at) for event in daily_signals
    ]
    assert_immutable_signals(
        (existing_detail or {}).get("items", [])
        if isinstance((existing_detail or {}).get("items"), list)
        else [],
        evaluated,
    )
    signal_dates = [_snapshot_date(snapshot) for snapshot in snapshots if _snapshot_date(snapshot)]
    snapshot_dates = set(signal_dates)
    snapshot_coverage_gaps = [
        trade_date
        for trade_date in calendar
        if signal_dates
        and min(signal_dates) <= trade_date <= max(signal_dates)
        and trade_date not in snapshot_dates
    ]
    latest_signal = max(signal_dates, default="")
    latest_price = max(
        (
            str(bar.get("date") or "")
            for stock in (cache.get("stocks") or {}).values()
            if isinstance(stock, dict)
            for bar in stock.get("bars") or []
            if isinstance(bar, dict)
        ),
        default="",
    )
    latest_benchmark = max(
        (
            str(bar.get("date") or "")
            for bar in cache.get("benchmark") or []
            if isinstance(bar, dict)
        ),
        default="",
    )
    detail = {
        "status": "ok" if evaluated else "failed",
        "ok": bool(evaluated),
        "validationVersion": VALIDATION_VERSION,
        "eventMode": "first_entry",
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latestSignalDate": latest_signal,
        "latestPriceDate": latest_price,
        "latestBenchmarkDate": latest_benchmark,
        "latest_trade_date": latest_signal,
        "itemsCount": len(evaluated),
        "dailyObservationCount": len(evaluated_daily),
        "snapshotCoverageGaps": snapshot_coverage_gaps,
        "definitions": {
            "entry": "First valid individual-stock trading-day open after signal date.",
            "d1": "Entry-day close.",
            "dN": "Nth valid individual-stock trading-day close, counting entry day as day one.",
            "returnFormula": "(target close / entry open - 1) * 100",
            "pendingValue": None,
            "benchmark": f"{BENCHMARK_CODE} {BENCHMARK_NAME}",
        },
        "signalCycleConfig": {
            "signalGapTolerance": SIGNAL_GAP_TOLERANCE,
            "newSignalAfterTradingDays": NEW_SIGNAL_AFTER_TRADING_DAYS,
            "newSignalAfterD20": True,
            "scoreVersionChangeStartsNewCycle": False,
            "missingSnapshotPolicy": "Unknown archive dates do not prove dropout, continuity, or re-entry.",
        },
        "successThresholds": {
            "absoluteSuccess": ABSOLUTE_SUCCESS_THRESHOLD,
            "maxAcceptableMae20": MAX_ACCEPTABLE_MAE_20,
        },
        "items": evaluated,
        "dailyObservations": evaluated_daily,
    }
    summary = build_summary(evaluated, signal_dates, generated_at)
    factors = build_factor_performance(evaluated, evaluated_daily, generated_at)
    portfolio = build_portfolio(evaluated, cache, calendar, generated_at)

    invalid_statuses = {
        "entry_price_unavailable",
        "price_data_incomplete",
        "suspended",
        "delisted",
        "error",
    }
    missing_price = sum(
        event.get("validationStatus") in invalid_statuses
        or "price_data_incomplete" in (event.get("statusFlags") or [])
        for event in evaluated
    )
    missing_benchmark = sum(
        "benchmark_unavailable" in (event.get("statusFlags") or [])
        for event in evaluated
    )
    latest_entry = max(
        (str(event.get("entryTradeDate") or "") for event in evaluated),
        default="",
    )
    source_status = cache.get("sourceStatus") if isinstance(cache.get("sourceStatus"), list) else []
    source_warnings = [
        str(row.get("error"))
        for row in source_status
        if isinstance(row, dict) and not row.get("ok") and row.get("error")
    ]
    warnings = list(dict.fromkeys(source_warnings))
    if not any(event.get("d5Return") is not None for event in evaluated):
        warnings.append("D+5 尚無到期樣本，相關統計保持 null。")
    if not any(event.get("d20Return") is not None for event in evaluated):
        warnings.append("D+20 尚無到期樣本，相關統計保持 null。")
    if missing_price:
        warnings.append(f"{missing_price} 筆訊號仍有個股行情缺口或無有效交易。")
    if missing_benchmark:
        warnings.append(f"{missing_benchmark} 筆訊號缺少同期 TAIEX benchmark。")
    if snapshot_coverage_gaps:
        warnings.append(
            "歷史 Top 10 快照缺少 "
            f"{len(snapshot_coverage_gaps)} 個交易日；缺口不推定為跌出或連續入榜。"
        )
    status_value = "ok" if evaluated and not warnings else "warning" if evaluated else "failed"
    status = {
        "status": status_value,
        "ok": bool(evaluated),
        "validationVersion": VALIDATION_VERSION,
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latestValidationUpdateTime": generated_at,
        "latestSignalDate": latest_signal,
        "latestEntryDate": latest_entry,
        "latestPriceDate": latest_price,
        "latestBenchmarkDate": latest_benchmark,
        "latest_trade_date": latest_signal,
        "completedSignals": summary["all"]["completedSignals"],
        "trackingSignals": summary["all"]["trackingSignals"],
        "d20CompletedSignals": sum(event.get("d20Return") is not None for event in evaluated),
        "missingPriceCount": missing_price,
        "missingBenchmarkCount": missing_benchmark,
        "snapshotCoverageGapCount": len(snapshot_coverage_gaps),
        "snapshotCoverageGaps": snapshot_coverage_gaps,
        "pipelineIntegrated": True,
        "previousDataPreserved": False,
        "lastError": "",
        "failedReasons": [],
        "warnings": warnings,
        "sourceStatus": source_status,
    }
    return {
        "ai-validation-detail.json": detail,
        "ai-validation-summary.json": summary,
        "ai-validation-portfolio.json": portfolio,
        "ai-factor-performance.json": factors,
        "ai-validation-status.json": status,
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
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


def write_bundle_transactional(
    payloads: dict[str, dict[str, Any]],
    output_dir: Path,
    docs_output_dir: Path,
    history_dir: Path,
    *,
    writer: Callable[[Path, Any], None] = _atomic_write_json,
) -> Path:
    """Write every validation artifact as one rollback-protected bundle."""
    required = set(OUTPUT_FILENAMES)
    missing = sorted(required - set(payloads))
    if missing:
        raise ValueError(f"validation bundle is missing outputs: {', '.join(missing)}")
    latest = (
        payloads["ai-validation-detail.json"].get("latestPriceDate")
        or payloads["ai-validation-detail.json"].get("latestSignalDate")
    )
    if not valid_iso_date(latest):
        raise ValueError("validation bundle has no valid snapshot date")
    history_path = history_dir / f"{latest}.json"
    destinations = [
        directory / name
        for directory in (output_dir, docs_output_dir)
        for name in OUTPUT_FILENAMES
    ] + [history_path]
    before = {path: path.read_bytes() if path.exists() else None for path in destinations}
    history_payload = {
        "validationVersion": VALIDATION_VERSION,
        "generatedAt": payloads["ai-validation-detail.json"].get("generatedAt"),
        "latestSignalDate": payloads["ai-validation-detail.json"].get("latestSignalDate"),
        "latestPriceDate": payloads["ai-validation-detail.json"].get("latestPriceDate"),
        "eventMode": "first_entry",
        "items": payloads["ai-validation-detail.json"].get("items", []),
        "summary": payloads["ai-validation-summary.json"].get("all", {}),
        "status": payloads["ai-validation-status.json"],
    }
    try:
        for directory in (output_dir, docs_output_dir):
            for name in OUTPUT_FILENAMES:
                writer(directory / name, payloads[name])
        writer(history_path, history_payload)
    except Exception:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        raise
    return history_path


def failed_status_payload(
    reason: str,
    previous_status: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_taipei().isoformat()
    previous_status = previous_status if isinstance(previous_status, dict) else {}
    return {
        **{
            key: previous_status.get(key)
            for key in (
                "latestSignalDate",
                "latestEntryDate",
                "latestPriceDate",
                "latestBenchmarkDate",
                "completedSignals",
                "trackingSignals",
                "d20CompletedSignals",
                "missingPriceCount",
                "missingBenchmarkCount",
            )
        },
        "status": "failed",
        "ok": False,
        "validationVersion": VALIDATION_VERSION,
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "latestValidationUpdateTime": generated_at,
        "latest_trade_date": previous_status.get("latest_trade_date") or "",
        "pipelineIntegrated": True,
        "previousDataPreserved": True,
        "lastError": reason,
        "failedReasons": [reason],
        "warnings": previous_status.get("warnings") or [],
    }
