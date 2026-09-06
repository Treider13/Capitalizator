"""Closed daily levels as entry obstacles, independent of intraday trend direction."""

from __future__ import annotations

import math
from typing import Any

DAY_SECONDS = 86400


def daily_context(series: dict[str, Any], price: float, at: float) -> dict[str, Any]:
    """Use the latest fully closed UTC day and only causally confirmed levels.

    A crossed horizontal level can be on either side of the current price. Its
    original kind is retained; this does not claim that a retest has occurred.
    """
    closed_at = series.get("at")
    result: dict[str, Any] = {
        "tf": "1d",
        "status": "warming",
        "at": closed_at,
        "bars": series.get("bars", 0),
        "support": None,
        "resistance": None,
        "levels": [],
    }
    if closed_at is None:
        return result
    if not math.isfinite(at) or closed_at != math.floor(at / DAY_SECONDS) * DAY_SECONDS:
        return {**result, "status": "stale"}
    if result["bars"] < 5:
        return result
    levels = [
        dict(p)
        for p in series.get("daily_levels", [])
        if 0 < p["price"] < math.inf and p["known_at"] <= closed_at
    ]
    if not levels:
        return result
    result.update(status="ready", levels=levels)
    if math.isfinite(price) and price > 0:
        supports = [p for p in levels if p["price"] <= price]
        resistances = [p for p in levels if p["price"] >= price]
        result["support"] = max(supports, key=lambda p: p["price"], default=None)
        result["resistance"] = min(resistances, key=lambda p: p["price"], default=None)
    return result


def daily_target(
    daily: dict[str, Any], side: int, entry: float, target: float, buffer: float, at: float
) -> dict[str, Any]:
    """Cap a target before the nearest daily level, without moving the stop."""
    status = daily.get("status", "missing")
    result: dict[str, Any] = {
        "allowed": False,
        "reason": "daily_context_" + status,
        "target": target,
        "limited": False,
        "level": None,
        "buffer": buffer,
        "at": daily.get("at"),
    }
    if status != "ready":
        return result
    if not math.isfinite(at) or daily.get("at") != math.floor(at / DAY_SECONDS) * DAY_SECONDS:
        return {**result, "reason": "daily_context_stale"}
    if side not in (-1, 1) or not all(0 < v < math.inf for v in (entry, target, buffer)):
        return {**result, "reason": "daily_context_invalid"}
    levels = daily.get("levels", [])
    if not levels:
        return {**result, "reason": "daily_context_warming"}
    ahead = [p for p in levels if side * (p["price"] - entry) >= 0]
    level = min(ahead, key=lambda p: side * (p["price"] - entry), default=None)
    if level is not None:
        capped = level["price"] - side * buffer
        if side * (target - capped) > 0:
            result.update(target=capped, limited=True)
    return {**result, "allowed": True, "reason": "ready", "level": level}
