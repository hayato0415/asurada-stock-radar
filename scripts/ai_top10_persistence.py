#!/usr/bin/env python
"""Persist official multi-factor Top 10 snapshots and tracking summaries.

This module never calculates a score. It only accepts rows produced by
``update_factor_scores.py`` and preserves the point-in-time ranking.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
DOCS_PROCESSED_DIR = ROOT / "docs" / "data" / "processed"
HISTORY_DIR = ROOT / "data" / "history" / "ai-top10"

DAILY_OUTPUT = PROCESSED_DIR / "ai-top10-daily.json"
HISTORY_OUTPUT = PROCESSED_DIR / "ai-top10-history.json"
WEEKLY_OUTPUT = PROCESSED_DIR / "ai-persistence-weekly.json"
MONTHLY_OUTPUT = PROCESSED_DIR / "ai-persistence-monthly.json"

OUTPUT_PATHS = (DAILY_OUTPUT, HISTORY_OUTPUT, WEEKLY_OUTPUT, MONTHLY_OUTPUT)
TAIPEI = timezone(timedelta(hours=8))

# All persistence labels and thresholds live here. Frontend code only renders
# the labels already produced by Python.
PERSISTENCE_RULES: dict[str, int | float] = {
    "top_n": 10,
    "weekly_trading_days": 5,
    "monthly_trading_days": 20,
    "stable_appearances_5d": 3,
    "monthly_resident_appearances_20d": 10,
    "score_weakening_consecutive_days": 3,
    "single_day_breakout_appearances_5d": 1,
}

REQUIRED_ITEM_FIELDS = (
    "rank",
    "code",
    "name",
    "market",
    "industry",
    "concepts",
    "close",
    "changePercent",
    "totalScore",
    "fundamentalScore",
    "technicalScore",
    "chipScore",
    "turnoverScore",
    "tradeType",
    "riskLabel",
    "dataDate",
    "generatedAt",
    "scoreVersion",
    "scoreSource",
)


def now_iso() -> str:
    return datetime.now(TAIPEI).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_bytes_atomic(path: Path, content: bytes) -> None:
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
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def write_json_atomic(path: Path, payload: Any) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_bytes_atomic(path, content)


def _snapshot_bytes(paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore_bytes(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            if path.exists():
                path.unlink()
        else:
            _write_bytes_atomic(path, content)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _symbol(item: dict[str, Any]) -> str:
    return str(item.get("code") or item.get("symbol") or "").strip()


def _score_trend(records: list[dict[str, Any]]) -> str:
    values = [_number(record.get("totalScore")) for record in records]
    scores = [value for value in values if value is not None]
    if len(scores) < 2:
        return "資料不足"
    delta = scores[-1] - scores[0]
    if delta > 0.05:
        return "上升"
    if delta < -0.05:
        return "下降"
    return "持平"


def _strictly_weakening(records: list[dict[str, Any]]) -> bool:
    required = int(PERSISTENCE_RULES["score_weakening_consecutive_days"])
    if len(records) < required:
        return False
    recent = records[-required:]
    scores = [_number(item.get("totalScore")) for item in recent]
    return all(value is not None for value in scores) and all(
        scores[index] < scores[index - 1]
        for index in range(1, len(scores))
    )


def _consecutive_days(snapshots: list[dict[str, Any]], code: str) -> int:
    count = 0
    for snapshot in reversed(snapshots):
        codes = {_symbol(item) for item in snapshot.get("items", []) if isinstance(item, dict)}
        if code not in codes:
            break
        count += 1
    return count


def validate_official_inputs(
    scores: list[dict[str, Any]],
    meta: dict[str, Any],
    status: dict[str, Any],
) -> tuple[str, str, dict[str, float], int]:
    if status.get("ok") is not True:
        raise ValueError(
            "正式多因子評分狀態不是成功，保留上一版持續入榜資料："
            f"{status.get('failed_reasons') or status.get('warnings') or 'unknown reason'}"
        )

    data_date = str(status.get("latest_trade_date") or meta.get("latest_trade_date") or "")
    meta_date = str(meta.get("latest_trade_date") or "")
    if not data_date or meta_date != data_date:
        raise ValueError(f"正式評分日期不同步：status={data_date or '--'}, meta={meta_date or '--'}")

    score_version = str(meta.get("score_version") or "")
    if not score_version:
        raise ValueError("factor-scores.meta.json 缺少 score_version")

    weights_payload = meta.get("weights")
    if not isinstance(weights_payload, dict):
        raise ValueError("factor-scores.meta.json 缺少正式權重")
    weights = {
        key: float(weights_payload.get(key))
        for key in ("fundamentalScore", "technicalScore", "chipScore", "turnoverScore")
    }
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"正式權重總和不是 1：{weights}")

    top_n = int(PERSISTENCE_RULES["top_n"])
    if len(scores) < top_n:
        raise ValueError(f"正式多因子評分只有 {len(scores)} 檔，無法建立 Top {top_n}")

    top_rows = scores[:top_n]
    codes = [_symbol(row) for row in top_rows]
    ranks = [row.get("rank") for row in top_rows]
    if any(not code for code in codes) or len(set(codes)) != top_n:
        raise ValueError("正式多因子 Top 10 股票代號缺漏或重複")
    if ranks != list(range(1, top_n + 1)):
        raise ValueError("正式多因子 Top 10 rank 必須為 1 到 10")

    for row in top_rows:
        if str(row.get("dataDate") or "") != data_date:
            raise ValueError(f"{_symbol(row)} dataDate 與正式日期不同步")
        factors = {
            key: _number(row.get(key))
            for key in ("fundamentalScore", "technicalScore", "chipScore", "turnoverScore")
        }
        if any(value is None for value in factors.values()):
            raise ValueError(f"{_symbol(row)} 缺少正式四因子分數")
        expected = round(sum(float(factors[key]) * weights[key] for key in weights), 1)
        actual = _number(row.get("totalScore"))
        if actual is None or not math.isclose(actual, expected, abs_tol=0.11):
            raise ValueError(f"{_symbol(row)} totalScore {actual} 與正式權重計算 {expected} 不符")

    quality = status.get("quality") if isinstance(status.get("quality"), dict) else {}
    valid_score_count = int(quality.get("score_candidates") or status.get("items_count") or len(scores))
    return data_date, score_version, weights, valid_score_count


def build_snapshot(
    scores: list[dict[str, Any]],
    *,
    data_date: str,
    generated_at: str,
    score_version: str,
    weights: dict[str, float],
    valid_score_count: int,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for rank, row in enumerate(scores[: int(PERSISTENCE_RULES["top_n"])], start=1):
        item = {
            "rank": rank,
            "code": _symbol(row),
            "name": str(row.get("name") or _symbol(row)),
            "market": str(row.get("market") or ""),
            "industry": str(row.get("industry") or ""),
            "concepts": list(row.get("concepts") or []),
            "close": row.get("close"),
            "changePercent": row.get("changePercent"),
            "totalScore": row.get("totalScore"),
            "fundamentalScore": row.get("fundamentalScore"),
            "technicalScore": row.get("technicalScore"),
            "chipScore": row.get("chipScore"),
            "turnoverScore": row.get("turnoverScore"),
            "tradeType": str(row.get("tradeType") or ""),
            "riskLabel": str(row.get("riskLabel") or ""),
            "dataDate": data_date,
            "generatedAt": generated_at,
            "scoreVersion": score_version,
            "scoreSource": str(row.get("scoreSource") or "factor-scores.json"),
        }
        items.append(item)

    return {
        "status": "ok",
        "ok": True,
        "dataDate": data_date,
        "latest_trade_date": data_date,
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "scoreVersion": score_version,
        "scoreSource": "docs/data/processed/factor-scores.json",
        "weights": weights,
        "validScoreCount": valid_score_count,
        "itemsCount": len(items),
        "items": items,
    }


def _validate_snapshot(snapshot: dict[str, Any], path: Path | None = None) -> None:
    label = str(path) if path else str(snapshot.get("dataDate") or "snapshot")
    items = snapshot.get("items")
    top_n = int(PERSISTENCE_RULES["top_n"])
    if snapshot.get("ok") is not True or not isinstance(items, list) or len(items) != top_n:
        raise ValueError(f"{label} 不是有效的每日 Top {top_n} 快照")
    ranks = [item.get("rank") for item in items if isinstance(item, dict)]
    codes = [_symbol(item) for item in items if isinstance(item, dict)]
    if ranks != list(range(1, top_n + 1)) or len(set(codes)) != top_n:
        raise ValueError(f"{label} rank 或股票代號不合法")
    for item in items:
        missing = [field for field in REQUIRED_ITEM_FIELDS if field not in item]
        if missing:
            raise ValueError(f"{label} {_symbol(item)} 缺少欄位：{', '.join(missing)}")


def load_history_snapshots(history_dir: Path = HISTORY_DIR) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    if not history_dir.exists():
        return snapshots
    seen_dates: set[str] = set()
    for path in sorted(history_dir.glob("*.json")):
        snapshot = read_json(path, {})
        if not isinstance(snapshot, dict):
            raise ValueError(f"{path} 不是 JSON 物件")
        _validate_snapshot(snapshot, path)
        data_date = str(snapshot.get("dataDate") or "")
        if data_date in seen_dates:
            raise ValueError(f"每日快照日期重複：{data_date}")
        if path.stem != data_date:
            raise ValueError(f"每日快照檔名 {path.stem} 與 dataDate {data_date} 不一致")
        seen_dates.add(data_date)
        snapshots.append(snapshot)
    snapshots.sort(key=lambda item: str(item.get("dataDate") or ""))
    return snapshots


def _window_stats(
    snapshots: list[dict[str, Any]],
    window_size: int,
    appearance_field: str,
    average_rank_field: str,
    best_rank_field: str,
    average_score_field: str,
    score_trend_field: str,
    include_rate: bool = False,
) -> dict[str, Any]:
    window = snapshots[-window_size:]
    records_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    latest_by_code: dict[str, dict[str, Any]] = {}
    for snapshot in window:
        date = str(snapshot.get("dataDate") or "")
        for item in snapshot.get("items", []):
            if not isinstance(item, dict):
                continue
            record = {**item, "_date": date}
            code = _symbol(item)
            records_by_code[code].append(record)
            latest_by_code[code] = item

    latest_items = {
        _symbol(item): item
        for item in (window[-1].get("items", []) if window else [])
        if isinstance(item, dict)
    }
    previous_items = {
        _symbol(item): item
        for item in (window[-2].get("items", []) if len(window) >= 2 else [])
        if isinstance(item, dict)
    }

    rows: list[dict[str, Any]] = []
    for code, records in records_by_code.items():
        ranks = [int(record["rank"]) for record in records]
        scores = [float(record["totalScore"]) for record in records]
        current = latest_items.get(code)
        previous = previous_items.get(code)
        latest_item = latest_by_code[code]
        row = {
            "code": code,
            "name": latest_item.get("name"),
            "market": latest_item.get("market"),
            "industry": latest_item.get("industry"),
            "concepts": latest_item.get("concepts") or [],
            appearance_field: len(records),
            average_rank_field: round(sum(ranks) / len(ranks), 2),
            best_rank_field: min(ranks),
            "latestRank": current.get("rank") if current else latest_item.get("rank"),
            "previousRank": previous.get("rank") if previous else None,
            "rankChange": (
                int(previous["rank"]) - int(current["rank"])
                if previous and current
                else None
            ),
            "consecutiveDays": _consecutive_days(window, code),
            average_score_field: round(sum(scores) / len(scores), 2),
            "latestScore": latest_item.get("totalScore"),
            score_trend_field: _score_trend(records),
            "firstSeenDate": records[0]["_date"],
            "lastSeenDate": records[-1]["_date"],
            "isCurrent": current is not None,
        }
        if include_rate:
            row["appearanceRate20d"] = round(len(records) / max(1, len(window)), 4)
        rows.append(row)

    rows.sort(
        key=lambda item: (
            -int(item[appearance_field]),
            float(item[average_rank_field]),
            -float(item["latestScore"]),
            -int(item["consecutiveDays"]),
            str(item["code"]),
        )
    )
    return {
        "status": "ok",
        "ok": True,
        "windowSize": window_size,
        "availableTradingDays": len(window),
        "tradingDates": [snapshot["dataDate"] for snapshot in window],
        "itemsCount": len(rows),
        "items": rows,
    }


def build_weekly_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return _window_stats(
        snapshots,
        int(PERSISTENCE_RULES["weekly_trading_days"]),
        "appearances5d",
        "averageRank5d",
        "bestRank5d",
        "averageScore5d",
        "scoreTrend",
    )


def build_monthly_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return _window_stats(
        snapshots,
        int(PERSISTENCE_RULES["monthly_trading_days"]),
        "appearances20d",
        "averageRank20d",
        "bestRank20d",
        "averageScore20d",
        "scoreTrend20d",
        include_rate=True,
    )


def _theme_concentration(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if key == "concepts":
            values = item.get("concepts") or [item.get("industry") or "未分類"]
        else:
            values = [item.get(key) or "未分類"]
        for value in dict.fromkeys(str(item_value or "未分類") for item_value in values):
            groups[value].append(
                {
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "rank": item.get("rank"),
                    "totalScore": item.get("totalScore"),
                }
            )
    rows = [
        {"name": name, "count": len(stocks), "stocks": sorted(stocks, key=lambda stock: stock["rank"])}
        for name, stocks in groups.items()
    ]
    rows.sort(key=lambda item: (-item["count"], item["name"]))
    return rows


def _status_labels(
    code: str,
    all_snapshots: list[dict[str, Any]],
    weekly_row: dict[str, Any],
    monthly_row: dict[str, Any],
) -> list[str]:
    current_index = len(all_snapshots) - 1
    previous_items = {
        _symbol(item)
        for item in (all_snapshots[-2].get("items", []) if len(all_snapshots) >= 2 else [])
        if isinstance(item, dict)
    }
    prior_items = {
        _symbol(item)
        for snapshot in all_snapshots[:-1]
        for item in snapshot.get("items", [])
        if isinstance(item, dict)
    }
    labels: list[str] = []
    if code not in previous_items:
        labels.append("重返榜" if code in prior_items else "新進榜")
    if int(weekly_row.get("consecutiveDays") or 0) >= 2:
        labels.append("連續入榜")
    rank_change = weekly_row.get("rankChange")
    if isinstance(rank_change, (int, float)) and rank_change > 0:
        labels.append("排名上升")
    elif isinstance(rank_change, (int, float)) and rank_change < 0:
        labels.append("排名下降")
    if int(weekly_row.get("appearances5d") or 0) >= int(PERSISTENCE_RULES["stable_appearances_5d"]):
        labels.append("穩定入榜")
    if int(monthly_row.get("appearances20d") or 0) >= int(
        PERSISTENCE_RULES["monthly_resident_appearances_20d"]
    ):
        labels.append("月度常駐")

    recent_records: list[dict[str, Any]] = []
    for snapshot in all_snapshots[: current_index + 1]:
        item = next(
            (
                candidate
                for candidate in snapshot.get("items", [])
                if isinstance(candidate, dict) and _symbol(candidate) == code
            ),
            None,
        )
        if item is None:
            recent_records = []
        else:
            recent_records.append(item)
    if _strictly_weakening(recent_records):
        labels.append("分數轉弱")
    return labels or ["持續觀察"]


def build_tracking_payloads(
    snapshots: list[dict[str, Any]],
    *,
    generated_at: str,
    valid_score_count: int,
    source_warnings: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not snapshots:
        raise ValueError("沒有可用的每日 Top 10 快照")
    latest = snapshots[-1]
    weekly = build_weekly_summary(snapshots)
    monthly = build_monthly_summary(snapshots)
    weekly_by_code = {item["code"]: item for item in weekly["items"]}
    monthly_by_code = {item["code"]: item for item in monthly["items"]}

    enriched_items: list[dict[str, Any]] = []
    for item in latest["items"]:
        code = _symbol(item)
        weekly_row = weekly_by_code[code]
        monthly_row = monthly_by_code[code]
        labels = _status_labels(code, snapshots, weekly_row, monthly_row)
        if (
            int(weekly_row.get("appearances5d") or 0)
            == int(PERSISTENCE_RULES["single_day_breakout_appearances_5d"])
            and item.get("riskLabel") == "過熱"
        ):
            labels.append("單日爆發")
        enriched_items.append(
            {
                **item,
                "previousRank": weekly_row.get("previousRank"),
                "rankChange": weekly_row.get("rankChange"),
                "appearances5d": weekly_row.get("appearances5d"),
                "appearances20d": monthly_row.get("appearances20d"),
                "consecutiveDays": weekly_row.get("consecutiveDays"),
                "scoreTrend": weekly_row.get("scoreTrend"),
                "entryStatus": labels[0],
                "statusLabels": labels,
            }
        )

    previous_items = {
        _symbol(item): item
        for item in (snapshots[-2].get("items", []) if len(snapshots) >= 2 else [])
        if isinstance(item, dict)
    }
    current_codes = {_symbol(item) for item in latest["items"]}
    dropped = [
        {
            **item,
            "previousRank": item.get("rank"),
            "latestRank": None,
            "entryStatus": "跌出榜",
            "statusLabels": ["跌出榜"],
        }
        for code, item in previous_items.items()
        if code not in current_codes
    ]
    new_entries = [
        item for item in enriched_items if item["entryStatus"] in {"新進榜", "重返榜"}
    ]
    continuous = [
        item for item in enriched_items if int(item.get("consecutiveDays") or 0) >= 2
    ]

    warnings = list(source_warnings or [])
    weekly_days = int(PERSISTENCE_RULES["weekly_trading_days"])
    monthly_days = int(PERSISTENCE_RULES["monthly_trading_days"])
    if len(snapshots) < weekly_days:
        warnings.append(f"歷史快照目前累積 {len(snapshots)} 個交易日，週榜尚未滿 {weekly_days} 日。")
    if len(snapshots) < monthly_days:
        warnings.append(f"歷史快照目前累積 {len(snapshots)} 個交易日，月榜尚未滿 {monthly_days} 日。")

    common = {
        "status": "ok",
        "ok": True,
        "latestTradeDate": latest["dataDate"],
        "latest_trade_date": latest["dataDate"],
        "generatedAt": generated_at,
        "generated_at": generated_at,
        "scoreVersion": latest["scoreVersion"],
        "scoreSource": latest["scoreSource"],
        "weights": latest["weights"],
        "rules": PERSISTENCE_RULES,
        "historyTradingDays": len(snapshots),
    }
    daily_payload = {
        **common,
        "validScoreCount": valid_score_count,
        "itemsCount": len(enriched_items),
        "warnings": warnings,
        "items": enriched_items,
        "continuous": continuous,
        "newEntrants": new_entries,
        "dropped": dropped,
        "industryConcentration": _theme_concentration(enriched_items, "industry"),
        "themeConcentration": _theme_concentration(enriched_items, "concepts"),
    }
    history_payload = {
        **common,
        "tradingDates": [snapshot["dataDate"] for snapshot in snapshots],
        "itemsCount": len(snapshots),
        "items": snapshots,
    }
    weekly_payload = {**common, **weekly}
    monthly_payload = {**common, **monthly}
    return daily_payload, history_payload, weekly_payload, monthly_payload


def generate_and_write(
    scores: list[dict[str, Any]],
    meta: dict[str, Any],
    status: dict[str, Any],
    *,
    output_dir: Path = PROCESSED_DIR,
    docs_output_dir: Path = DOCS_PROCESSED_DIR,
    history_dir: Path = HISTORY_DIR,
    generated_at: str | None = None,
    writer: Callable[[Path, Any], None] = write_json_atomic,
) -> dict[str, Any]:
    generated_at = generated_at or now_iso()
    data_date, score_version, weights, valid_score_count = validate_official_inputs(scores, meta, status)

    output_paths = (
        output_dir / DAILY_OUTPUT.name,
        output_dir / HISTORY_OUTPUT.name,
        output_dir / WEEKLY_OUTPUT.name,
        output_dir / MONTHLY_OUTPUT.name,
    )
    docs_paths = tuple(docs_output_dir / path.name for path in output_paths)
    snapshot_path = history_dir / f"{data_date}.json"
    rollback = _snapshot_bytes(output_paths + docs_paths + (snapshot_path,))

    try:
        existing_snapshot = read_json(snapshot_path, None)
        if existing_snapshot is not None:
            if not isinstance(existing_snapshot, dict):
                raise ValueError(f"{snapshot_path} 不是有效 JSON 物件")
            _validate_snapshot(existing_snapshot, snapshot_path)
            if str(existing_snapshot.get("dataDate") or "") != data_date:
                raise ValueError(f"{snapshot_path} 日期不一致")
            snapshot = existing_snapshot
            snapshot_created = False
        else:
            snapshot = build_snapshot(
                scores,
                data_date=data_date,
                generated_at=generated_at,
                score_version=score_version,
                weights=weights,
                valid_score_count=valid_score_count,
            )
            _validate_snapshot(snapshot)
            snapshot_created = True
            writer(snapshot_path, snapshot)

        snapshots = load_history_snapshots(history_dir)
        if not any(item.get("dataDate") == data_date for item in snapshots):
            snapshots.append(snapshot)
            snapshots.sort(key=lambda item: item["dataDate"])

        daily, history, weekly, monthly = build_tracking_payloads(
            snapshots,
            generated_at=generated_at,
            valid_score_count=valid_score_count,
            source_warnings=list(status.get("warnings") or []),
        )
        payloads = (daily, history, weekly, monthly)
        for path, payload in zip(output_paths, payloads):
            writer(path, payload)
        for path, payload in zip(docs_paths, payloads):
            writer(path, payload)
    except Exception:
        _restore_bytes(rollback)
        raise

    try:
        snapshot_label = str(snapshot_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        snapshot_label = str(snapshot_path)

    return {
        "ok": True,
        "status": "ok",
        "latest_trade_date": data_date,
        "generated_at": generated_at,
        "snapshot_created": snapshot_created,
        "snapshot_path": snapshot_label,
        "history_trading_days": len(snapshots),
        "items_count": int(PERSISTENCE_RULES["top_n"]),
        "previous_data_preserved": False,
        "failed_reasons": [],
        "outputs": {
            DAILY_OUTPUT.name: "updated",
            HISTORY_OUTPUT.name: "updated",
            WEEKLY_OUTPUT.name: "updated",
            MONTHLY_OUTPUT.name: "updated",
        },
    }
