from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.ai_top10_persistence import (
    PERSISTENCE_RULES,
    build_monthly_summary,
    build_snapshot,
    build_tracking_payloads,
    build_weekly_summary,
    generate_and_write,
)


WEIGHTS = {
    "fundamentalScore": 0.30,
    "technicalScore": 0.30,
    "chipScore": 0.25,
    "turnoverScore": 0.15,
}


def score_row(code: str, rank: int, data_date: str, total_offset: float = 0) -> dict:
    fundamental = 90 - rank + total_offset
    technical = 85 - rank + total_offset
    chip = 80 - rank + total_offset
    turnover = 75 - rank + total_offset
    total = round(
        fundamental * WEIGHTS["fundamentalScore"]
        + technical * WEIGHTS["technicalScore"]
        + chip * WEIGHTS["chipScore"]
        + turnover * WEIGHTS["turnoverScore"],
        1,
    )
    return {
        "rank": rank,
        "code": code,
        "symbol": code,
        "name": f"股票{code}",
        "market": "上市",
        "industry": "半導體業",
        "concepts": ["AI"],
        "close": 100 + rank,
        "changePercent": 1.5,
        "fundamentalScore": fundamental,
        "technicalScore": technical,
        "chipScore": chip,
        "turnoverScore": turnover,
        "totalScore": total,
        "tradeType": "波段",
        "riskLabel": "正常",
        "dataDate": data_date,
        "scoreSource": "official_quote_valuation_revenue",
    }


def official_inputs(data_date: str, offset: float = 0) -> tuple[list[dict], dict, dict]:
    scores = [score_row(f"{1000 + rank}", rank, data_date, offset) for rank in range(1, 11)]
    meta = {
        "latest_trade_date": data_date,
        "score_version": "official-multifactor-v1",
        "weights": WEIGHTS,
    }
    status = {
        "ok": True,
        "latest_trade_date": data_date,
        "warnings": [],
        "quality": {"score_candidates": 1900},
    }
    return scores, meta, status


def synthetic_snapshot(data_date: str, codes: list[str], score_shift: float = 0) -> dict:
    rows = [score_row(code, rank, data_date, score_shift) for rank, code in enumerate(codes, start=1)]
    return build_snapshot(
        rows,
        data_date=data_date,
        generated_at=f"{data_date}T18:00:00+08:00",
        score_version="official-multifactor-v1",
        weights=WEIGHTS,
        valid_score_count=1900,
    )


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.output_dir = root / "data" / "processed"
        self.docs_dir = root / "docs" / "data" / "processed"
        self.history_dir = root / "data" / "history" / "ai-top10"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def generate(self, data_date: str, offset: float = 0, generated_at: str | None = None) -> dict:
        scores, meta, status = official_inputs(data_date, offset)
        return generate_and_write(
            scores,
            meta,
            status,
            output_dir=self.output_dir,
            docs_output_dir=self.docs_dir,
            history_dir=self.history_dir,
            generated_at=generated_at or f"{data_date}T18:00:00+08:00",
        )

    def test_same_date_rerun_does_not_duplicate_or_overwrite_snapshot(self) -> None:
        self.generate("2026-07-20")
        snapshot_path = self.history_dir / "2026-07-20.json"
        original = snapshot_path.read_bytes()

        result = self.generate("2026-07-20", offset=8)
        history = json.loads((self.output_dir / "ai-top10-history.json").read_text(encoding="utf-8"))
        daily = json.loads((self.output_dir / "ai-top10-daily.json").read_text(encoding="utf-8"))

        self.assertFalse(result["snapshot_created"])
        self.assertEqual(snapshot_path.read_bytes(), original)
        self.assertEqual(history["tradingDates"], ["2026-07-20"])
        self.assertEqual(daily["items"][0]["totalScore"], json.loads(original)["items"][0]["totalScore"])

    def test_holiday_run_does_not_create_a_fake_trading_date(self) -> None:
        self.generate("2026-07-17", generated_at="2026-07-17T18:00:00+08:00")
        self.generate("2026-07-17", generated_at="2026-07-19T08:00:00+08:00")
        self.assertEqual([path.name for path in self.history_dir.glob("*.json")], ["2026-07-17.json"])

    def test_five_day_statistics_are_correct(self) -> None:
        snapshots = []
        start = date(2026, 7, 13)
        for index in range(5):
            codes = ["A"] + [f"{index}{rank}" for rank in range(1, 10)]
            if index == 1:
                codes = [f"{index}{rank}" for rank in range(10)]
            snapshots.append(synthetic_snapshot((start + timedelta(days=index)).isoformat(), codes, index))
        row = next(item for item in build_weekly_summary(snapshots)["items"] if item["code"] == "A")
        self.assertEqual(row["appearances5d"], 4)
        self.assertEqual(row["bestRank5d"], 1)
        self.assertEqual(row["averageRank5d"], 1.0)

    def test_twenty_day_statistics_are_correct(self) -> None:
        snapshots = []
        start = date(2026, 6, 1)
        for index in range(20):
            codes = ["A"] + [f"{index:02d}{rank}" for rank in range(1, 10)]
            if index < 5:
                codes = [f"{index:02d}{rank}" for rank in range(10)]
            snapshots.append(synthetic_snapshot((start + timedelta(days=index)).isoformat(), codes, index / 10))
        row = next(item for item in build_monthly_summary(snapshots)["items"] if item["code"] == "A")
        self.assertEqual(row["appearances20d"], 15)
        self.assertEqual(row["appearanceRate20d"], 0.75)
        self.assertEqual(row["bestRank20d"], 1)

    def test_consecutive_days_are_counted_from_latest_trading_day(self) -> None:
        snapshots = []
        start = date(2026, 7, 1)
        for index in range(5):
            codes = [f"{index}{rank}" for rank in range(10)]
            if index >= 2:
                codes[0] = "A"
            snapshots.append(synthetic_snapshot((start + timedelta(days=index)).isoformat(), codes))
        row = next(item for item in build_weekly_summary(snapshots)["items"] if item["code"] == "A")
        self.assertEqual(row["consecutiveDays"], 3)

    def test_new_entry_and_dropped_entry_are_generated(self) -> None:
        day_one = synthetic_snapshot("2026-07-20", list("ABCDEFGHIJ"))
        day_two = synthetic_snapshot("2026-07-21", list("BCDEFGHIJK"))
        daily, _, _, _ = build_tracking_payloads(
            [day_one, day_two],
            generated_at="2026-07-21T18:00:00+08:00",
            valid_score_count=1900,
        )
        self.assertEqual([item["code"] for item in daily["newEntrants"]], ["K"])
        self.assertEqual([item["code"] for item in daily["dropped"]], ["A"])
        self.assertEqual(daily["newEntrants"][0]["entryStatus"], "新進榜")

    def test_old_snapshot_is_not_changed_by_new_weights(self) -> None:
        self.generate("2026-07-20")
        old_path = self.history_dir / "2026-07-20.json"
        old_bytes = old_path.read_bytes()

        scores, meta, status = official_inputs("2026-07-21")
        new_weights = {
            "fundamentalScore": 0.25,
            "technicalScore": 0.35,
            "chipScore": 0.25,
            "turnoverScore": 0.15,
        }
        meta["weights"] = new_weights
        for row in scores:
            row["totalScore"] = round(
                sum(row[key] * new_weights[key] for key in new_weights),
                1,
            )
        generate_and_write(
            scores,
            meta,
            status,
            output_dir=self.output_dir,
            docs_output_dir=self.docs_dir,
            history_dir=self.history_dir,
            generated_at="2026-07-21T18:00:00+08:00",
        )

        self.assertEqual(old_path.read_bytes(), old_bytes)
        history = json.loads((self.output_dir / "ai-top10-history.json").read_text(encoding="utf-8"))
        self.assertEqual(history["items"][0]["weights"], WEIGHTS)

    def test_failed_update_preserves_previous_outputs(self) -> None:
        self.generate("2026-07-20")
        before = {
            path.name: path.read_bytes()
            for path in self.output_dir.glob("ai-*.json")
        }
        scores, meta, status = official_inputs("2026-07-21")
        status["ok"] = False
        status["failed_reasons"] = ["official source failed"]

        with self.assertRaises(ValueError):
            generate_and_write(
                scores,
                meta,
                status,
                output_dir=self.output_dir,
                docs_output_dir=self.docs_dir,
                history_dir=self.history_dir,
            )

        after = {path.name: path.read_bytes() for path in self.output_dir.glob("ai-*.json")}
        self.assertEqual(after, before)
        self.assertFalse((self.history_dir / "2026-07-21.json").exists())


if __name__ == "__main__":
    unittest.main()
