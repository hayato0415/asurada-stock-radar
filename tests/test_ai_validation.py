from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts import ai_validation as av
from scripts import update_ai_validation as uav


GENERATED_AT = "2026-07-23T18:00:00+08:00"


def valid_days_after(signal_date: str, count: int) -> list[str]:
    current = date.fromisoformat(signal_date)
    values: list[str] = []
    while len(values) < count:
        current += timedelta(days=1)
        if current.weekday() < 5:
            values.append(current.isoformat())
    return values


def score_item(
    code: str = "2330",
    *,
    rank: int = 1,
    version: str = "official-multifactor-v1",
    close: float = 100.0,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "code": code,
        "name": f"Stock {code}",
        "market": "twse",
        "industry": "Semiconductor",
        "concepts": ["AI"],
        "scoreVersion": version,
        "totalScore": 80.0 - rank,
        "fundamentalScore": 80.0,
        "technicalScore": 78.0,
        "chipScore": 76.0,
        "turnoverScore": 74.0,
        "close": close,
        "changePercent": 2.5,
        "tradeType": "breakout",
        "riskLabel": "normal",
        "entryStatus": "new",
        "consecutiveDays": 1,
        "appearances5d": 1,
        "appearances20d": 1,
        "statusLabels": [],
    }


def snapshot(
    data_date: str,
    items: list[dict[str, Any]] | None = None,
    *,
    version: str = "official-multifactor-v1",
) -> dict[str, Any]:
    rows = copy.deepcopy(items if items is not None else [score_item(version=version)])
    for row in rows:
        row.setdefault("scoreVersion", version)
    return {
        "status": "ok",
        "ok": True,
        "dataDate": data_date,
        "latest_trade_date": data_date,
        "scoreVersion": version,
        "items": rows,
    }


def price_bar(
    trade_date: str,
    *,
    open_price: float | None = 100.0,
    high: float | None = None,
    low: float | None = None,
    close: float | None = 100.0,
    has_trade: bool = True,
    volume: int = 1000,
) -> dict[str, Any]:
    reference = close if close is not None else open_price
    return {
        "date": trade_date,
        "open": open_price,
        "high": high if high is not None else reference,
        "low": low if low is not None else reference,
        "close": close,
        "volume": volume,
        "hasTrade": has_trade,
        "rawPresent": True,
        "source": "official-test-fixture",
    }


def cache_for(
    signal_date: str,
    stock_bars: dict[str, list[dict[str, Any]]],
    *,
    calendar: list[str] | None = None,
    benchmark: list[dict[str, Any]] | None = None,
    coverage_ok: bool = True,
) -> dict[str, Any]:
    all_dates = {
        str(row["date"])
        for bars in stock_bars.values()
        for row in bars
        if row.get("date")
    }
    calendar_values = sorted(set(calendar or []) | all_dates | {signal_date})
    coverage = {
        "twse": {
            value: {"ok": coverage_ok}
            for value in calendar_values
            if value > signal_date
        }
    }
    return {
        "calendar": calendar_values,
        "stocks": {
            code: {"market": "twse", "bars": copy.deepcopy(bars)}
            for code, bars in stock_bars.items()
        },
        "benchmark": copy.deepcopy(benchmark or []),
        "coverage": coverage,
        "sourceStatus": [],
    }


def evaluate_one(
    signal_date: str,
    cache: dict[str, Any],
    *,
    item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events, _, calendar = av.build_signal_cycles(
        [snapshot(signal_date, [item or score_item()])],
        cache,
    )
    return av.evaluate_signal(events[0], cache, calendar, GENERATED_AT)


def minimal_bundle_payloads(latest: str = "2026-07-06") -> dict[str, dict[str, Any]]:
    return {
        "ai-validation-detail.json": {
            "ok": True,
            "generatedAt": GENERATED_AT,
            "latestSignalDate": "2026-07-03",
            "latestPriceDate": latest,
            "items": [],
        },
        "ai-validation-summary.json": {"ok": True, "all": {"totalSignals": 0}},
        "ai-validation-portfolio.json": {"ok": True, "holding5": {}, "holding20": {}},
        "ai-factor-performance.json": {"ok": True, "firstEntry": {}, "dailyObservation": {}},
        "ai-validation-status.json": {
            "ok": True,
            "status": "ok",
            "generatedAt": GENERATED_AT,
        },
    }


class AiValidationTests(unittest.TestCase):
    def test_01_friday_signal_enters_on_monday_open(self) -> None:
        signal_date = "2026-07-03"
        monday = "2026-07-06"
        cache = cache_for(signal_date, {"2330": [price_bar(monday, open_price=101.0)]})
        result = evaluate_one(signal_date, cache)
        self.assertEqual(result["entryTradeDate"], monday)
        self.assertEqual(result["entryOpen"], 101.0)

    def test_02_market_holiday_is_not_counted_as_entry_day(self) -> None:
        signal_date = "2026-07-03"
        first_post_holiday_session = "2026-07-07"
        cache = cache_for(
            signal_date,
            {"2330": [price_bar(first_post_holiday_session, open_price=102.0)]},
            calendar=[signal_date, first_post_holiday_session],
        )
        result = evaluate_one(signal_date, cache)
        self.assertEqual(result["entryTradeDate"], first_post_holiday_session)

    def test_03_d5_uses_fifth_valid_trading_day(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 5)
        bars = [price_bar(value, close=100.0 + index) for index, value in enumerate(dates, 1)]
        result = evaluate_one(signal_date, cache_for(signal_date, {"2330": bars}))
        self.assertEqual(result["d5TradeDate"], dates[4])
        self.assertEqual(result["d5Close"], 105.0)

    def test_04_d20_uses_twentieth_valid_trading_day(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 20)
        bars = [price_bar(value, close=100.0 + index) for index, value in enumerate(dates, 1)]
        result = evaluate_one(signal_date, cache_for(signal_date, {"2330": bars}))
        self.assertEqual(result["d20TradeDate"], dates[19])
        self.assertEqual(result["trackingStatus"], "completed")

    def test_05_suspended_stock_day_is_skipped(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 2)
        bars = [
            price_bar(dates[0], has_trade=False, volume=0),
            price_bar(dates[1], open_price=103.0, close=104.0),
        ]
        result = evaluate_one(signal_date, cache_for(signal_date, {"2330": bars}))
        self.assertEqual(result["entryTradeDate"], dates[1])
        self.assertEqual(result["entryOpen"], 103.0)

    def test_06_signal_close_is_never_used_as_entry_price(self) -> None:
        signal_date = "2026-07-03"
        entry_date = valid_days_after(signal_date, 1)[0]
        item = score_item(close=999.0)
        cache = cache_for(
            signal_date,
            {"2330": [price_bar(entry_date, open_price=123.0, close=125.0)]},
        )
        result = evaluate_one(signal_date, cache, item=item)
        self.assertEqual(result["signalClose"], 999.0)
        self.assertEqual(result["entryOpen"], 123.0)
        self.assertNotEqual(result["entryOpen"], result["signalClose"])

    def test_07_missing_entry_open_is_not_backfilled(self) -> None:
        signal_date = "2026-07-03"
        entry_date = valid_days_after(signal_date, 1)[0]
        bar = price_bar(entry_date, open_price=None, high=105.0, low=95.0, close=100.0)
        result = evaluate_one(signal_date, cache_for(signal_date, {"2330": [bar]}))
        self.assertEqual(result["validationStatus"], "entry_price_unavailable")
        self.assertFalse(result["entryPriceAvailable"])
        self.assertIsNone(result["entryOpen"])

    def test_08_signal_waits_when_next_session_has_not_arrived(self) -> None:
        signal_date = "2026-07-03"
        result = evaluate_one(
            signal_date,
            cache_for(signal_date, {}, calendar=[signal_date]),
        )
        self.assertEqual(result["validationStatus"], "waiting_entry")
        for period in av.PERIODS:
            self.assertIsNone(result[f"d{period}Return"])

    def test_09_not_yet_due_periods_remain_null(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 3)
        bars = [price_bar(value, close=100.0 + index) for index, value in enumerate(dates, 1)]
        result = evaluate_one(signal_date, cache_for(signal_date, {"2330": bars}))
        self.assertIsNotNone(result["d1Return"])
        self.assertIsNotNone(result["d3Return"])
        self.assertIsNone(result["d5Return"])
        self.assertIsNone(result["d10Return"])
        self.assertIsNone(result["d20Return"])
        self.assertIn("D+20", result["pendingPeriods"])

    def test_10_return_formula_uses_target_close_over_entry_open(self) -> None:
        self.assertEqual(av.calculate_return(110.0, 100.0), 10.0)
        self.assertEqual(av.calculate_return(90.0, 100.0), -10.0)
        self.assertIsNone(av.calculate_return(110.0, 0.0))

    def test_11_mfe_uses_highest_high_from_entry_open(self) -> None:
        bars = [
            price_bar("2026-07-06", high=110.0, low=95.0),
            price_bar("2026-07-07", high=120.0, low=98.0),
        ]
        mfe, _, highest, _ = av.calculate_mfe_mae(bars, 100.0)
        self.assertEqual(mfe, 20.0)
        self.assertEqual(highest, 120.0)

    def test_12_mae_uses_lowest_low_and_is_negative(self) -> None:
        bars = [
            price_bar("2026-07-06", high=110.0, low=95.0),
            price_bar("2026-07-07", high=120.0, low=90.0),
        ]
        _, mae, _, lowest = av.calculate_mfe_mae(bars, 100.0)
        self.assertEqual(mae, -10.0)
        self.assertEqual(lowest, 90.0)

    def test_13_max_drawdown_uses_peak_to_subsequent_low(self) -> None:
        bars = [
            price_bar("2026-07-06", high=120.0, low=95.0),
            price_bar("2026-07-07", high=110.0, low=90.0),
        ]
        self.assertEqual(av.calculate_max_drawdown(bars, 100.0), -25.0)

    def test_14_incomplete_ohlc_keeps_path_risk_null(self) -> None:
        bars = [
            price_bar("2026-07-06", high=110.0, low=None),
        ]
        bars[0]["low"] = None
        mfe, mae, _, _ = av.calculate_mfe_mae(bars, 100.0)
        self.assertIsNone(mfe)
        self.assertIsNone(mae)
        self.assertIsNone(av.calculate_max_drawdown(bars, 100.0))

    def test_15_continuous_listings_create_one_first_entry_event(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
        snapshots = [snapshot(value) for value in dates]
        events, daily, _ = av.build_signal_cycles(
            snapshots,
            cache_for(dates[0], {}, calendar=dates),
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["consecutiveDays"], 3)
        self.assertEqual(len(daily), 3)

    def test_16_one_trading_day_gap_extends_same_cycle(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
        events, _, _ = av.build_signal_cycles(
            [
                snapshot(dates[0]),
                snapshot(dates[1], [score_item("2317")]),
                snapshot(dates[2]),
            ],
            cache_for(dates[0], {}, calendar=dates),
        )
        target_events = [event for event in events if event["code"] == "2330"]
        self.assertEqual(len(target_events), 1)
        self.assertTrue(target_events[0]["reentered"])

    def test_17_two_trading_day_gap_starts_new_cycle(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06"]
        events, _, _ = av.build_signal_cycles(
            [
                snapshot(dates[0]),
                snapshot(dates[1], [score_item("2317")]),
                snapshot(dates[2], [score_item("2317")]),
                snapshot(dates[3]),
            ],
            cache_for(dates[0], {}, calendar=dates),
        )
        target_events = [event for event in events if event["code"] == "2330"]
        self.assertEqual(len(target_events), 2)
        self.assertEqual(
            [event["signalCycleNumber"] for event in target_events],
            [1, 2],
        )

    def test_18_new_cycle_starts_after_d20_completion(self) -> None:
        signal_date = "2026-06-01"
        future_dates = valid_days_after(signal_date, 21)
        all_dates = [signal_date, *future_dates]
        snapshots = [snapshot(value) for value in all_dates]
        bars = [price_bar(value, close=100.0 + index / 10) for index, value in enumerate(future_dates)]
        events, _, _ = av.build_signal_cycles(
            snapshots,
            cache_for(signal_date, {"2330": bars}, calendar=all_dates),
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["signalDate"], future_dates[20])
        self.assertTrue(events[1]["reentered"])

    def test_19_score_version_change_does_not_open_overlapping_cycle(self) -> None:
        dates = ["2026-07-01", "2026-07-02"]
        snapshots = [
            snapshot(dates[0], version="v1"),
            snapshot(dates[1], version="v2"),
        ]
        events, daily, _ = av.build_signal_cycles(
            snapshots,
            cache_for(dates[0], {}, calendar=dates),
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["scoreVersion"], "v1")
        self.assertEqual({event["scoreVersion"] for event in daily}, {"v1", "v2"})

    def test_19b_missing_snapshot_does_not_prove_continuity_or_reentry(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
        snapshots = [snapshot(dates[0]), snapshot(dates[2])]
        cache = cache_for(dates[0], {}, calendar=dates)
        events, daily, _ = av.build_signal_cycles(snapshots, cache)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["reentered"])
        self.assertEqual(daily[-1]["entryStatus"], "快照缺口待確認")
        self.assertEqual(daily[-1]["consecutiveDays"], 1)
        bundle = av.build_validation_bundle(
            snapshots,
            cache,
            generated_at=GENERATED_AT,
        )
        self.assertEqual(
            bundle["ai-validation-detail.json"]["snapshotCoverageGaps"],
            [dates[1]],
        )

    def test_20_same_date_rerun_is_idempotent(self) -> None:
        signal_date = "2026-07-03"
        cache = cache_for(signal_date, {}, calendar=[signal_date])
        first = av.build_validation_bundle(
            [snapshot(signal_date)],
            cache,
            generated_at=GENERATED_AT,
        )
        second = av.build_validation_bundle(
            [snapshot(signal_date)],
            cache,
            existing_detail=first["ai-validation-detail.json"],
            generated_at=GENERATED_AT,
        )
        first_ids = [item["signalId"] for item in first["ai-validation-detail.json"]["items"]]
        second_ids = [item["signalId"] for item in second["ai-validation-detail.json"]["items"]]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(len(second_ids), len(set(second_ids)))

    def test_21_duplicate_input_code_does_not_duplicate_first_entry_signal(self) -> None:
        signal_date = "2026-07-03"
        duplicate_rows = [score_item("2330", rank=1), score_item("2330", rank=2)]
        events, _, _ = av.build_signal_cycles(
            [snapshot(signal_date, duplicate_rows)],
            cache_for(signal_date, {}, calendar=[signal_date]),
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(len({event["signalId"] for event in events}), 1)

    def test_22_dropped_stock_remains_in_tracking_history(self) -> None:
        dates = ["2026-07-01", "2026-07-02"]
        snapshots = [
            snapshot(dates[0], [score_item("2330")]),
            snapshot(dates[1], [score_item("2317")]),
        ]
        events, _, _ = av.build_signal_cycles(
            snapshots,
            cache_for(dates[0], {}, calendar=dates),
        )
        by_code = {event["code"]: event for event in events}
        self.assertIn("2330", by_code)
        self.assertTrue(by_code["2330"]["droppedOut"])

    def test_23_daily_observations_are_separate_from_first_entry_events(self) -> None:
        dates = ["2026-07-01", "2026-07-02"]
        events, daily, _ = av.build_signal_cycles(
            [snapshot(value) for value in dates],
            cache_for(dates[0], {}, calendar=dates),
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(len(daily), 2)
        self.assertEqual(events[0]["signalMode"], "first_entry")
        self.assertTrue(all(item["signalMode"] == "daily_observation" for item in daily))

    def test_23b_first_entry_groups_do_not_learn_future_persistence(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
        events, daily, _ = av.build_signal_cycles(
            [snapshot(value) for value in dates],
            cache_for(dates[0], {}, calendar=dates),
        )
        self.assertIn("新進榜", events[0]["entrySignalTypes"])
        self.assertNotIn("連續入榜 3 日以上", events[0]["signalTypes"])
        self.assertIn("連續入榜 3 日以上", daily[-1]["signalTypes"])
        factors = av.build_factor_performance(events, daily, GENERATED_AT)
        first_labels = {
            row["label"]
            for row in factors["firstEntry"]["groups"]["signalTypes"]
        }
        daily_labels = {
            row["label"]
            for row in factors["dailyObservation"]["groups"]["signalTypes"]
        }
        self.assertNotIn("連續入榜 3 日以上", first_labels)
        self.assertIn("連續入榜 3 日以上", daily_labels)

    def test_24_immutable_signal_change_is_rejected(self) -> None:
        prior = {
            "signalId": "2330_2026-07-03_v1",
            "signalDate": "2026-07-03",
            "code": "2330",
            "signalScore": 80.0,
        }
        changed = {**prior, "signalScore": 81.0}
        with self.assertRaisesRegex(ValueError, "immutable signal"):
            av.assert_immutable_signals([prior], [changed])

    def test_25_maturing_outcomes_do_not_change_immutable_signal(self) -> None:
        prior = {
            "signalId": "2330_2026-07-03_v1",
            "signalDate": "2026-07-03",
            "code": "2330",
            "signalScore": 80.0,
            "d5Return": None,
        }
        matured = {**prior, "d5Return": 5.0, "validationStatus": "partially_completed"}
        av.assert_immutable_signals([prior], [matured])

    def test_26_pending_d20_is_excluded_from_win_rate_denominator(self) -> None:
        events = [
            {"d20Return": 10.0, "outperformedBenchmarkD20": True},
            {"d20Return": -5.0, "outperformedBenchmarkD20": False},
            {"d20Return": None, "outperformedBenchmarkD20": None},
        ]
        stats = av.period_statistics(events, 20)
        self.assertEqual(stats["completedSamples"], 2)
        self.assertEqual(stats["winRate"], 50.0)
        self.assertEqual(stats["benchmarkWinRate"], 50.0)

    def test_27_average_and_median_statistics_are_correct(self) -> None:
        events = [{"d5Return": value} for value in (1.0, 3.0, 100.0)]
        stats = av.period_statistics(events, 5)
        self.assertEqual(stats["averageReturn"], round(104.0 / 3.0, 4))
        self.assertEqual(stats["medianReturn"], 3.0)

    def test_28_recent_and_monthly_summaries_use_signal_dates(self) -> None:
        dates = [
            "2026-06-30",
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
            "2026-07-06",
            "2026-07-07",
        ]
        events = [
            {
                "signalId": f"A_{value}",
                "signalDate": value,
                "d1Return": 1.0,
                "trackingStatus": "tracking",
                "validationStatus": "tracking",
            }
            for value in dates
        ]
        summary = av.build_summary(events, dates, GENERATED_AT)
        self.assertEqual(summary["recent5"]["totalSignals"], 5)
        self.assertEqual(summary["recent20"]["totalSignals"], 6)
        self.assertEqual(set(summary["monthly"]), {"2026-06", "2026-07"})

    def test_29_benchmark_return_and_excess_return_are_calculated(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 5)
        stock_bars = [
            price_bar(value, open_price=100.0, close=101.0 + index)
            for index, value in enumerate(dates)
        ]
        benchmark = [
            {
                "date": value,
                "open": 1000.0 if index == 0 else 1000.0 + index,
                "high": 1010.0 + index,
                "low": 990.0 + index,
                "close": 1004.0 + index * 4,
            }
            for index, value in enumerate(dates)
        ]
        result = evaluate_one(
            signal_date,
            cache_for(signal_date, {"2330": stock_bars}, benchmark=benchmark),
        )
        self.assertEqual(result["benchmarkD5Return"], 2.0)
        self.assertEqual(result["d5Return"], 5.0)
        self.assertEqual(result["excessReturnD5"], 3.0)
        self.assertTrue(result["outperformedBenchmarkD5"])

    def test_30_missing_benchmark_is_null_not_zero(self) -> None:
        signal_date = "2026-07-03"
        entry_date = valid_days_after(signal_date, 1)[0]
        result = evaluate_one(
            signal_date,
            cache_for(signal_date, {"2330": [price_bar(entry_date, close=105.0)]}),
        )
        self.assertIsNone(result["benchmarkD1Return"])
        self.assertIsNone(result["excessReturnD1"])
        self.assertIn("benchmark_unavailable", result["statusFlags"])

    def test_31_score_versions_are_grouped_separately(self) -> None:
        events = [
            {
                "signalDate": "2026-07-01",
                "scoreVersion": version,
                "fundamentalScore": 80.0,
                "technicalScore": 80.0,
                "chipScore": 80.0,
                "turnoverScore": 80.0,
                "signalTypes": ["new"],
                "tradeType": "breakout",
                "riskLabel": "normal",
                "d5Return": 5.0,
            }
            for version in ("v1", "v2")
        ]
        payload = av.build_factor_performance(events, [], GENERATED_AT)
        groups = payload["firstEntry"]["groups"]["scoreVersions"]
        self.assertEqual({row["label"] for row in groups}, {"v1", "v2"})

    def test_32_sample_labels_respect_insufficient_and_normal_thresholds(self) -> None:
        insufficient = av.sample_label(9)
        observation = av.sample_label(10)
        normal = av.sample_label(30)
        self.assertNotEqual(insufficient, observation)
        self.assertNotEqual(observation, normal)
        self.assertEqual(av.sample_label(29), observation)

    def test_33_equal_weight_portfolio_averages_active_positions(self) -> None:
        signal_date = "2026-07-03"
        entry_date = valid_days_after(signal_date, 1)[0]
        rows = [score_item("A", rank=1), score_item("B", rank=2)]
        cache = cache_for(
            signal_date,
            {
                "A": [price_bar(entry_date, open_price=100.0, close=110.0)],
                "B": [price_bar(entry_date, open_price=100.0, close=90.0)],
            },
        )
        events, _, calendar = av.build_signal_cycles([snapshot(signal_date, rows)], cache)
        evaluated = [av.evaluate_signal(event, cache, calendar, GENERATED_AT) for event in events]
        curve = av.build_portfolio_curve(evaluated, cache, calendar, 1)
        self.assertEqual(curve["rows"][0]["holdingCount"], 2)
        self.assertEqual(curve["rows"][0]["grossReturn"], 0.0)

    def test_34_transaction_costs_reduce_net_portfolio_return(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 5)
        bars = [
            price_bar(value, open_price=100.0, close=110.0, high=111.0, low=99.0)
            for value in dates
        ]
        cache = cache_for(signal_date, {"2330": bars})
        events, _, calendar = av.build_signal_cycles([snapshot(signal_date)], cache)
        evaluated = [av.evaluate_signal(events[0], cache, calendar, GENERATED_AT)]
        portfolio = av.build_portfolio(evaluated, cache, calendar, GENERATED_AT)
        self.assertLess(portfolio["holding5"]["netReturn"], portfolio["holding5"]["grossReturn"])
        assumption = portfolio["costAssumption"]
        self.assertEqual(
            assumption["roundTripRate"],
            round(
                av.BUY_COMMISSION_RATE
                + av.SELL_COMMISSION_RATE
                + av.SELL_TRANSACTION_TAX_RATE,
                6,
            ),
        )
        self.assertTrue(assumption["netReturnIncludesCosts"])

    def test_35_transactional_write_rolls_back_every_destination(self) -> None:
        payloads = minimal_bundle_payloads()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "data" / "processed"
            docs = root / "docs" / "data" / "processed"
            history = root / "data" / "history" / "ai-validation"
            history_path = history / "2026-07-06.json"
            destinations = [
                directory / name
                for directory in (output, docs)
                for name in av.OUTPUT_FILENAMES
            ] + [history_path]
            for path in destinations:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"previous-good-data")

            calls = 0

            def failing_writer(path: Path, payload: Any) -> None:
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("simulated write failure")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(OSError, "simulated write failure"):
                av.write_bundle_transactional(
                    payloads,
                    output,
                    docs,
                    history,
                    writer=failing_writer,
                )
            self.assertTrue(all(path.read_bytes() == b"previous-good-data" for path in destinations))

    def test_36_transactional_write_creates_parseable_mirrors_and_history(self) -> None:
        payloads = minimal_bundle_payloads()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "data" / "processed"
            docs = root / "docs" / "data" / "processed"
            history = root / "data" / "history" / "ai-validation"
            history_path = av.write_bundle_transactional(payloads, output, docs, history)
            for name in av.OUTPUT_FILENAMES:
                root_payload = json.loads((output / name).read_text(encoding="utf-8"))
                docs_payload = json.loads((docs / name).read_text(encoding="utf-8"))
                self.assertEqual(root_payload, docs_payload)
            self.assertTrue(json.loads(history_path.read_text(encoding="utf-8"))["status"]["ok"])

    def test_37_all_generated_payloads_round_trip_as_json(self) -> None:
        signal_date = "2026-07-03"
        bundle = av.build_validation_bundle(
            [snapshot(signal_date)],
            cache_for(signal_date, {}, calendar=[signal_date]),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(set(bundle), set(av.OUTPUT_FILENAMES))
        for payload in bundle.values():
            self.assertEqual(json.loads(json.dumps(payload, ensure_ascii=False)), payload)

    def test_38_generated_signal_dates_are_iso_or_null(self) -> None:
        signal_date = "2026-07-03"
        entry_date = valid_days_after(signal_date, 1)[0]
        bundle = av.build_validation_bundle(
            [snapshot(signal_date)],
            cache_for(signal_date, {"2330": [price_bar(entry_date)]}),
            generated_at=GENERATED_AT,
        )
        item = bundle["ai-validation-detail.json"]["items"][0]
        date_fields = [
            "signalDate",
            "entryTradeDate",
            *[f"d{period}TradeDate" for period in av.PERIODS],
        ]
        for field in date_fields:
            value = item.get(field)
            self.assertTrue(value is None or av.valid_iso_date(value) == value, field)

    def test_39_output_contains_only_codes_present_in_historical_snapshots(self) -> None:
        signal_date = "2026-07-03"
        input_codes = {"2330", "2317"}
        bundle = av.build_validation_bundle(
            [snapshot(signal_date, [score_item(code) for code in sorted(input_codes)])],
            cache_for(signal_date, {}, calendar=[signal_date]),
            generated_at=GENERATED_AT,
        )
        output_codes = {
            item["code"]
            for item in bundle["ai-validation-detail.json"]["items"]
        }
        self.assertEqual(output_codes, input_codes)
        self.assertEqual(
            len(bundle["ai-validation-detail.json"]["items"]),
            len({item["signalId"] for item in bundle["ai-validation-detail.json"]["items"]}),
        )

    def test_40_partial_price_gap_warns_without_failing_entire_bundle(self) -> None:
        signal_date = "2026-07-03"
        future_date = valid_days_after(signal_date, 1)[0]
        cache = cache_for(
            signal_date,
            {},
            calendar=[signal_date, future_date],
            coverage_ok=False,
        )
        bundle = av.build_validation_bundle(
            [snapshot(signal_date)],
            cache,
            generated_at=GENERATED_AT,
        )
        detail = bundle["ai-validation-detail.json"]
        status = bundle["ai-validation-status.json"]
        self.assertTrue(detail["ok"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["status"], "warning")
        self.assertEqual(status["missingPriceCount"], 1)
        self.assertIsNone(detail["items"][0]["d1Return"])

    def test_41_failed_status_preserves_previous_counts_and_records_reason(self) -> None:
        previous = {
            "latestSignalDate": "2026-07-03",
            "latest_trade_date": "2026-07-03",
            "completedSignals": 12,
            "warnings": ["old warning"],
        }
        failed = av.failed_status_payload(
            "official source failed",
            previous,
            generated_at=GENERATED_AT,
        )
        self.assertFalse(failed["ok"])
        self.assertTrue(failed["previousDataPreserved"])
        self.assertEqual(failed["completedSignals"], 12)
        self.assertEqual(failed["lastError"], "official source failed")

    def test_42_frontend_fetch_contract_has_timeout_and_abort(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "assets" / "js" / "api.js").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_FETCH_TIMEOUT_MS", source)
        self.assertIn("AbortController", source)
        self.assertIn("setTimeout", source)
        self.assertIn("clearTimeout", source)

    def test_43_radar_frontend_renders_partial_fetch_failures(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "assets" / "js" / "radar-page.js").read_text(encoding="utf-8")
        self.assertIn("renderValidationFailureBlock", source)
        self.assertIn("summaryResult?.data", source)
        self.assertIn("detailResult?.data", source)
        self.assertIn("renderValidation(loaded)", source)

    def test_44_data_status_frontend_clears_loading_state_in_finally(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "assets" / "js" / "data-status-page.js").read_text(encoding="utf-8")
        self.assertIn("renderFailure", source)
        self.assertIn("catch (error)", source)
        self.assertIn("finally", source)
        self.assertIn("button.disabled = false", source)

    def test_45_partial_tracking_keeps_progress_but_flags_invalid_price_data(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 2)
        cache = cache_for(
            signal_date,
            {"2330": [price_bar(dates[0], close=101.0)]},
            calendar=[signal_date, *dates],
        )
        cache["coverage"]["twse"][dates[1]] = {"ok": False}
        result = evaluate_one(signal_date, cache)
        self.assertEqual(result["trackingStatus"], "tracking")
        self.assertEqual(result["validationStatus"], "price_data_incomplete")

    def test_46_portfolio_suspension_is_not_reweighted_or_forward_filled(self) -> None:
        signal_date = "2026-07-03"
        dates = valid_days_after(signal_date, 3)
        bars = [
            price_bar(dates[0], close=101.0),
            price_bar(dates[1], close=None, has_trade=False, volume=0),
            price_bar(dates[2], close=102.0),
        ]
        cache = cache_for(signal_date, {"2330": bars})
        events, _, calendar = av.build_signal_cycles([snapshot(signal_date)], cache)
        evaluated = [
            av.evaluate_signal(events[0], cache, calendar, GENERATED_AT)
        ]
        curve = av.build_portfolio_curve(evaluated, cache, calendar, 5)
        self.assertEqual(curve["status"], "price_data_incomplete")
        self.assertEqual(curve["rows"], [])
        self.assertIsNone(curve["grossReturn"])

    def test_47_portfolio_benchmark_starts_at_first_invested_day_open(self) -> None:
        signal_date = "2026-07-03"
        entry_date = valid_days_after(signal_date, 1)[0]
        benchmark = [
            {
                "date": signal_date,
                "open": 900.0,
                "high": 910.0,
                "low": 890.0,
                "close": 900.0,
            },
            {
                "date": entry_date,
                "open": 1000.0,
                "high": 1020.0,
                "low": 990.0,
                "close": 1010.0,
            },
        ]
        cache = cache_for(
            signal_date,
            {"2330": [price_bar(entry_date, close=101.0)]},
            benchmark=benchmark,
        )
        events, _, calendar = av.build_signal_cycles([snapshot(signal_date)], cache)
        evaluated = [
            av.evaluate_signal(events[0], cache, calendar, GENERATED_AT)
        ]
        curve = av.build_portfolio_curve(evaluated, cache, calendar, 1)
        self.assertEqual(curve["rows"][0]["benchmarkDailyReturn"], 1.0)

    def test_48_group_benchmark_rates_have_explicit_horizons(self) -> None:
        events = [
            {
                "d5Return": 1.0,
                "d20Return": 2.0,
                "outperformedBenchmarkD5": True,
                "outperformedBenchmarkD20": False,
            }
        ]
        metrics = av._group_metrics(events)
        self.assertEqual(metrics["benchmarkOutperformanceRateD5"], 100.0)
        self.assertEqual(metrics["benchmarkOutperformanceRateD20"], 0.0)
        self.assertEqual(metrics["benchmarkOutperformanceHorizon"], "D+5")


class AiValidationMarketRefreshTests(unittest.TestCase):
    @staticmethod
    def references(required: int = 1) -> dict[str, dict[str, int]]:
        return {
            market: {
                "masterRows": required,
                "previousMatchedRows": required,
                "referenceRows": required,
                "requiredRows": required,
            }
            for market in ("twse", "tpex")
        }

    @staticmethod
    def taiex_rows(*dates: str) -> list[dict[str, Any]]:
        return [
            {
                "date": value,
                "open": 20000,
                "high": 20100,
                "low": 19900,
                "close": 20050,
                "source": "official-taiex-test",
            }
            for value in dates
        ]

    @staticmethod
    def quote(close: float) -> dict[str, Any]:
        return {
            "open_price": close - 1,
            "high_price": close + 1,
            "low_price": close - 2,
            "trade_price": close,
            "volume": 1000,
            "transactions": 100,
        }

    def test_tracked_stocks_retains_every_immutable_market_for_symbol(self) -> None:
        listed = score_item()
        listed["market"] = "twse"
        otc = score_item()
        otc["market"] = "tpex"
        tracked = uav._tracked_stocks(
            [
                snapshot("2026-07-01", [listed]),
                snapshot("2026-07-02", [otc]),
            ]
        )
        self.assertEqual(tracked["2330"], {"twse", "tpex"})

    def test_market_reference_uses_larger_master_or_previous_population(self) -> None:
        master = {
            "items": [
                {"code": "1101", "market": "twse"},
                {"code": "1102", "market": "twse"},
                {"code": "6488", "market": "tpex"},
            ]
        }
        refs = uav._market_reference_counts(
            master,
            {"twse_quote_matched": 10, "tpex_quote_matched": 5},
        )
        self.assertEqual(refs["twse"]["referenceRows"], 10)
        self.assertEqual(refs["twse"]["requiredRows"], 10)
        self.assertEqual(refs["tpex"]["requiredRows"], 5)

    def test_85_percent_response_is_not_verified_as_full_market(self) -> None:
        refs = uav._market_reference_counts(
            [{"code": str(index), "market": "twse"} for index in range(100)],
            {},
        )
        assessment = uav._assess_full_market_coverage(
            "twse",
            85,
            refs["twse"],
        )
        self.assertEqual(refs["twse"]["requiredRows"], 100)
        self.assertFalse(assessment["coverageVerified"])

    def test_low_row_response_is_not_full_market_coverage(self) -> None:
        assessment = uav._assess_full_market_coverage(
            "twse",
            7,
            {
                "masterRows": 100,
                "previousMatchedRows": 90,
                "referenceRows": 100,
                "requiredRows": 80,
            },
        )
        self.assertFalse(assessment["ok"])
        self.assertFalse(assessment["coverageVerified"])
        self.assertIn("incomplete", assessment["error"])

    def test_partial_response_keeps_present_quote_without_fake_absence(self) -> None:
        signal_date = "2026-07-01"
        trade_date = "2026-07-02"
        item = score_item()
        item["market"] = "twse"
        with (
            patch.object(uav, "read_json", return_value={}),
            patch.object(
                uav,
                "fetch_taiex_month",
                return_value=(
                    self.taiex_rows(signal_date, trade_date),
                    "official-taiex-test",
                ),
            ),
            patch.object(
                uav,
                "fetch_daily_quotes_exact",
                return_value=([{"row": 1}], trade_date, "official-twse-test"),
            ),
            patch.object(
                uav,
                "parse_quote_rows",
                return_value=({"2330": self.quote(101)}, trade_date),
            ),
        ):
            refreshed = uav.refresh_market_cache(
                [snapshot(signal_date, [item])],
                {},
                as_of_date=trade_date,
                market_references=self.references(required=50),
            )
        coverage = refreshed["coverage"]["twse"][trade_date]
        bar = refreshed["stocks"]["2330"]["barsByMarket"]["twse"][0]
        self.assertFalse(coverage["ok"])
        self.assertTrue(bar["rawPresent"])
        self.assertEqual(bar["market"], "twse")

    def test_verified_response_can_record_explicit_absence(self) -> None:
        signal_date = "2026-07-01"
        trade_date = "2026-07-02"
        item = score_item()
        item["market"] = "twse"
        other_quotes = {
            f"{1000 + index}": self.quote(100 + index)
            for index in range(5)
        }
        with (
            patch.object(uav, "read_json", return_value={}),
            patch.object(
                uav,
                "fetch_taiex_month",
                return_value=(
                    self.taiex_rows(signal_date, trade_date),
                    "official-taiex-test",
                ),
            ),
            patch.object(
                uav,
                "fetch_daily_quotes_exact",
                return_value=([{"row": 1}] * 5, trade_date, "official-twse-test"),
            ),
            patch.object(
                uav,
                "parse_quote_rows",
                return_value=(other_quotes, trade_date),
            ),
        ):
            refreshed = uav.refresh_market_cache(
                [snapshot(signal_date, [item])],
                {},
                as_of_date=trade_date,
                market_references=self.references(required=5),
            )
        coverage = refreshed["coverage"]["twse"][trade_date]
        bar = refreshed["stocks"]["2330"]["barsByMarket"]["twse"][0]
        self.assertTrue(coverage["coverageVerified"])
        self.assertFalse(bar["rawPresent"])

    def test_cross_market_symbol_bars_are_saved_separately(self) -> None:
        signal_date = "2026-07-01"
        trade_date = "2026-07-03"
        listed = score_item()
        listed["market"] = "twse"
        otc = score_item()
        otc["market"] = "tpex"

        def parse_rows(
            raw_rows: list[dict[str, Any]],
            label: str,
            source_url: str,
        ) -> tuple[dict[str, dict[str, Any]], str]:
            close = 101 if "twse" in source_url else 202
            return {"2330": self.quote(close)}, trade_date

        with (
            patch.object(uav, "read_json", return_value={}),
            patch.object(
                uav,
                "fetch_taiex_month",
                return_value=(
                    self.taiex_rows(signal_date, trade_date),
                    "official-taiex-test",
                ),
            ),
            patch.object(
                uav,
                "fetch_daily_quotes_exact",
                side_effect=lambda market, value: (
                    [{"row": 1}],
                    value,
                    f"official-{market}-test",
                ),
            ),
            patch.object(uav, "parse_quote_rows", side_effect=parse_rows),
        ):
            refreshed = uav.refresh_market_cache(
                [
                    snapshot(signal_date, [listed]),
                    snapshot("2026-07-02", [otc]),
                ],
                {},
                as_of_date=trade_date,
                market_references=self.references(),
            )
        stock = refreshed["stocks"]["2330"]
        self.assertEqual(stock["markets"], ["tpex", "twse"])
        self.assertEqual(stock["market"], "tpex")
        self.assertEqual(stock["barsByMarket"]["twse"][0]["close"], 101)
        self.assertEqual(stock["barsByMarket"]["tpex"][0]["close"], 202)
        self.assertEqual(av._stock_bars(refreshed, "2330", "twse")[trade_date]["close"], 101)
        self.assertEqual(av._stock_bars(refreshed, "2330", "tpex")[trade_date]["close"], 202)

    def test_future_cached_rows_are_removed_by_as_of_cutoff(self) -> None:
        signal_date = "2026-07-01"
        cutoff = "2026-07-02"
        future = "2026-07-03"
        item = score_item()
        item["market"] = "twse"
        existing = {
            "benchmark": [price_bar(cutoff), price_bar(future)],
            "stocks": {
                "2330": {
                    "market": "twse",
                    "bars": [
                        {**price_bar(cutoff), "market": "twse"},
                        {**price_bar(future), "market": "twse"},
                    ],
                }
            },
            "coverage": {
                "twse": {
                    cutoff: {"ok": True, "coverageVerified": True},
                    future: {"ok": True, "coverageVerified": True},
                }
            },
        }
        with patch.object(uav, "read_json", return_value={}):
            refreshed = uav.refresh_market_cache(
                [snapshot(signal_date, [item])],
                existing,
                as_of_date=cutoff,
                allow_network=False,
                market_references=self.references(),
            )
        self.assertEqual(
            [row["date"] for row in refreshed["stocks"]["2330"]["bars"]],
            [cutoff],
        )
        self.assertEqual([row["date"] for row in refreshed["benchmark"]], [cutoff])
        self.assertNotIn(future, refreshed["coverage"]["twse"])

    def test_total_required_market_source_failure_raises(self) -> None:
        signal_date = "2026-07-01"
        trade_date = "2026-07-02"
        item = score_item()
        item["market"] = "twse"
        with (
            patch.object(uav, "read_json", return_value={}),
            patch.object(
                uav,
                "fetch_taiex_month",
                return_value=(
                    self.taiex_rows(signal_date, trade_date),
                    "official-taiex-test",
                ),
            ),
            patch.object(
                uav,
                "fetch_daily_quotes_exact",
                side_effect=RuntimeError("TWSE unavailable"),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "required post-signal official market data unavailable",
            ):
                uav.refresh_market_cache(
                    [snapshot(signal_date, [item])],
                    {},
                    as_of_date=trade_date,
                    market_references=self.references(),
                )

    def test_run_preserves_outputs_and_returns_nonzero_on_required_source_failure(
        self,
    ) -> None:
        previous = {
            "latestSignalDate": "2026-07-01",
            "completedSignals": 12,
        }
        with (
            patch.object(uav, "load_top10_snapshots", return_value=[snapshot("2026-07-01")]),
            patch.object(uav, "read_json", side_effect=[previous, {}]),
            patch.object(
                uav,
                "refresh_market_cache",
                side_effect=RuntimeError("required official market source unavailable"),
            ),
            patch.object(uav, "_atomic_write_json") as atomic_write,
            patch.object(uav, "write_outputs") as write_outputs,
        ):
            result = uav.run(as_of_date="2026-07-02")
        self.assertEqual(result, 1)
        write_outputs.assert_not_called()
        self.assertEqual(atomic_write.call_count, 2)
        failed_payload = atomic_write.call_args_list[0].args[1]
        self.assertTrue(failed_payload["previousDataPreserved"])
        self.assertEqual(failed_payload["completedSignals"], 12)


if __name__ == "__main__":
    unittest.main()
