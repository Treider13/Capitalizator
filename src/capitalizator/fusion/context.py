"""Causal context descriptors with explicit operational definitions.

Pattern names are labels for measurable geometry, not claims about participant
identity or intentions. Only closed bars and already confirmed pivots are used.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from capitalizator.card.rsi import stream_rsi
from capitalizator.card.sweep import fractals


def sessions(at: float) -> dict[str, str]:
    """Overlapping venue-independent local research sessions; DST from IANA tzdata."""
    result = {}
    for name, zone, start, end in (
        ("asia", "Asia/Tokyo", 9, 18),
        ("london", "Europe/London", 8, 17),
        ("new_york", "America/New_York", 8, 17),
    ):
        local = datetime.fromtimestamp(at, UTC).astimezone(ZoneInfo(zone))
        if start <= local.hour < end:
            result[name] = str(local.date())
    return result


def session_windows(start: float, end: float) -> list[dict[str, Any]]:
    """Exact UTC session boundaries, including boundaries inside 4h candles."""
    windows = []
    for name, zone, first, last in (
        ("Tokyo", "Asia/Tokyo", 9, 18),
        ("London", "Europe/London", 8, 17),
        ("NY", "America/New_York", 8, 17),
    ):
        tz = ZoneInfo(zone)
        day = datetime.fromtimestamp(start, tz).replace(hour=0, minute=0, second=0, microsecond=0)
        while day.timestamp() <= end:
            for label, hour in (("open", first), ("close", last)):
                at = day.replace(hour=hour).timestamp()
                if start <= at <= end:
                    windows.append({"name": name, "boundary": label, "at": at})
            day += timedelta(days=1)
    return sorted(windows, key=lambda r: r["at"])


def rank(value: float, history: list[float]) -> float | None:
    if not history:
        return None
    return sum(v <= value for v in history) / len(history)


def geometry(bars: list[Any], tick: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bag": None,
        "triangle": None,
        "flag": None,
        "rsi_divergence": None,
        "trend": None,
        "equal_highs": [],
        "equal_lows": [],
        "atr": None,
        "order_block_zone": None,
        "rsi": None,
    }
    if len(bars) < 3:
        return result
    closes = [float(b.close) for b in bars]
    result["rsi"] = stream_rsi(closes, period=14, unstable=0)
    high, low = [float(b.high) for b in bars], [float(b.low) for b in bars]
    tr = [
        max(high[i] - low[i], abs(high[i] - closes[i - 1]), abs(low[i] - closes[i - 1]))
        for i in range(1, len(bars))
    ]
    result["atr"] = float(np.mean(tr[-14:]))
    # BAG here means a true two-bar non-overlap outside the preceding range.
    if low[-1] > high[-2] and closes[-1] > max(high[:-1]):
        result["bag"] = {"side": "bull", "low": high[-2], "high": low[-1]}
    elif high[-1] < low[-2] and closes[-1] < min(low[:-1]):
        result["bag"] = {"side": "bear", "low": high[-1], "high": low[-2]}
    highs, lows = fractals(bars, n=2)
    for label, pivots, values in (("equal_highs", highs, high), ("equal_lows", lows, low)):
        counts: dict[int, int] = {}
        for i in pivots:
            level = round(values[i] / tick)
            counts[level] = counts.get(level, 0) + 1
        result[label] = [level * tick for level, count in counts.items() if count >= 2]
    if len(highs) >= 2 and len(lows) >= 2:
        hi, lo = highs[-2:], lows[-2:]
        hs = (high[hi[1]] - high[hi[0]]) / (hi[1] - hi[0])
        ls = (low[lo[1]] - low[lo[0]]) / (lo[1] - lo[0])
        trend = 1 if hs > 0 and ls > 0 else -1 if hs < 0 and ls < 0 else 0
        result["trend"] = trend
        result["trend_lines"] = {
            "high": [[i, high[i]] for i in hi],
            "low": [[i, low[i]] for i in lo],
        }
        result["trend_segments"] = {
            "high": [[bars[i].open_ts.timestamp(), high[i]] for i in hi],
            "low": [[bars[i].open_ts.timestamp(), low[i]] for i in lo],
        }
        result["triangle"] = bool(hs < 0 < ls)
        anchor = min(hi[0], lo[0])
        impulse = closes[anchor] - closes[0]
        # A flag is an opposing parallel channel after a larger directional leg.
        result["flag"] = bool(
            trend * impulse < 0 and abs(impulse) > max(high[anchor:]) - min(low[anchor:])
        )
    for pivots, values, side in ((lows, low, 1), (highs, high, -1)):
        if len(pivots) < 2:
            continue
        first, last = pivots[-2:]
        r1 = stream_rsi(closes[: first + 1], period=14, unstable=0)
        r2 = stream_rsi(closes[: last + 1], period=14, unstable=0)
        if r1 is not None and r2 is not None:
            if side * (values[last] - values[first]) < 0 and side * (r2 - r1) > 0:
                result["rsi_divergence"] = {"side": side, "pivots": [first, last], "rsi": [r1, r2]}
                result["rsi_divergence"]["segment"] = [
                    [bars[i].open_ts.timestamp(), values[i]] for i in (first, last)
                ]
    direction = (
        1
        if highs and closes[-1] > high[highs[-1]]
        else (-1 if lows and closes[-1] < low[lows[-1]] else 0)
    )
    for bar in reversed(bars[:-1]) if direction else []:
        if direction * float(bar.close - bar.open) < 0:
            result["order_block_zone"] = {
                "side": direction,
                "low": float(bar.low),
                "high": float(bar.high),
            }
            break
    return result


def absorption(flow: float, refill: float, price_return: float, volatility: float) -> float:
    """Signed replenishment against aggressors with weak price response; not iceberg proof."""
    opposing = max(0.0, -flow * refill)
    return math.copysign(opposing, refill) * math.exp(-abs(price_return) / max(volatility, 1e-12))
