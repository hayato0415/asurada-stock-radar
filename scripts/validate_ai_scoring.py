from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "config" / "scoring-weights.json"
META_PATH = ROOT / "data" / "latest" / "scoring-meta.json"
RANKING_PATH = ROOT / "data" / "latest" / "ai-ranking-top100.json"
SCORECARD_DIR = ROOT / "data" / "scorecards"

EXPECTED_WEIGHTS = {
    "fundamental": 30,
    "technical": 30,
    "chip": 25,
    "turnover": 15,
}
BAD_THEME_CODES = {"04", "05", "06", "07", "08"}


def read_json(path: Path) -> Any:
    if not path.exists():
        raise AssertionError(f"Missing required file: {path.relative_to(ROOT)}")
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def get_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def assert_close(label: str, actual: Any, expected: Any, tolerance: float = 0.15) -> None:
    if math.fabs(num(actual) - num(expected)) > tolerance:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def validate_config(config: dict[str, Any]) -> None:
    modules = config.get("modules", {})
    if set(modules) != set(EXPECTED_WEIGHTS):
        raise AssertionError(f"Config modules must be {sorted(EXPECTED_WEIGHTS)}, got {sorted(modules)}")
    for key, weight in EXPECTED_WEIGHTS.items():
        actual = modules.get(key, {}).get("weight")
        if actual != weight:
            raise AssertionError(f"Config weight for {key} must be {weight}, got {actual}")
    if sum(module.get("weight", 0) for module in modules.values()) != 100:
        raise AssertionError("Config module weights must sum to 100")
    if config.get("news_scoring", {}).get("included") is not False or config.get("news_scoring", {}).get("weight") != 0:
        raise AssertionError("News scoring must be disabled with weight 0")
    if config.get("theme_scoring", {}).get("included") is not False or config.get("theme_scoring", {}).get("weight") != 0:
        raise AssertionError("Theme scoring must be disabled with weight 0")


def validate_scorecard(card: dict[str, Any], expected_build_id: str) -> list[str]:
    warnings: list[str] = []
    symbol = str(card.get("symbol") or "")
    if card.get("build_id") != expected_build_id:
        raise AssertionError(f"{symbol}: scorecard build_id mismatch")
    modules = card.get("modules", {})
    if set(modules) != set(EXPECTED_WEIGHTS):
        raise AssertionError(f"{symbol}: scorecard modules must be {sorted(EXPECTED_WEIGHTS)}, got {sorted(modules)}")
    total_from_modules = 0.0
    for key, weight in EXPECTED_WEIGHTS.items():
        module = modules.get(key, {})
        if module.get("weight") != weight:
            raise AssertionError(f"{symbol}: {key} weight must be {weight}, got {module.get('weight')}")
        if not isinstance(module.get("rules"), list) or not module["rules"]:
            raise AssertionError(f"{symbol}: {key} must include scoring rules")
        total_from_modules += num(module.get("score"))
    assert_close(f"{symbol}: total_score", card.get("total_score"), round(total_from_modules, 1))
    summary = card.get("summary", {})
    assert_close(f"{symbol}: summary total_score", summary.get("total_score"), card.get("total_score"))
    if card.get("news_scoring", {}).get("included") is not False:
        raise AssertionError(f"{symbol}: news scoring must be disabled")
    if card.get("theme_scoring", {}).get("included") is not False:
        raise AssertionError(f"{symbol}: theme scoring must be disabled")
    if "news" in modules or "theme" in modules:
        raise AssertionError(f"{symbol}: news/theme module must not exist")
    theme = str(card.get("theme") or summary.get("theme") or "")
    if theme in BAD_THEME_CODES:
        warnings.append(f"{symbol}: suspicious theme code {theme}")
    return warnings


def main() -> int:
    warnings: list[str] = []
    config = read_json(CONFIG_PATH)
    meta = read_json(META_PATH)
    ranking = read_json(RANKING_PATH)
    validate_config(config)

    build_id = ranking.get("build_id")
    if not build_id:
        raise AssertionError("ai-ranking-top100.json must include build_id")
    if meta.get("build_id") != build_id:
        raise AssertionError("scoring-meta.json build_id must match ai-ranking-top100.json")

    items = get_items(ranking)
    if not items:
        raise AssertionError("ai-ranking-top100.json items must not be empty")
    if len(items) > 100:
        raise AssertionError("ai-ranking-top100.json must contain at most 100 items")

    themes = {str(item.get("theme") or "") for item in items}
    if themes == {"未分類"}:
        raise AssertionError("All ranking themes are 未分類; taxonomy fallback is broken")
    for item in items:
        symbol = str(item.get("symbol") or item.get("code") or "")
        if not symbol:
            raise AssertionError("Ranking item missing symbol")
        if item.get("news_scoring_included") is not False:
            raise AssertionError(f"{symbol}: ranking item must mark news_scoring_included=false")
        if item.get("theme_scoring_included") is not False:
            raise AssertionError(f"{symbol}: ranking item must mark theme_scoring_included=false")
        card_path = SCORECARD_DIR / f"{symbol}.json"
        card = read_json(card_path)
        warnings.extend(validate_scorecard(card, build_id))

    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"AI scoring validation OK: {len(items)} ranking rows, build_id={build_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"AI scoring validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
