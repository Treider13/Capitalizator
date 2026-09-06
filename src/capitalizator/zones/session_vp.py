"""Session volume-at-price. Not L2. Not TradingView request.footprint().

Each closed working-TF bar spreads its volume evenly across ticks in [low, high]
(the same OHLC estimate VP scripts document). Value area is 70% grown from the
POC the way bfolkens/py-market-profile does (VALUE_AREA_FRAC). Empty volume →
no zone, never POC=close.

Windows are the last *closed* asia/europe/overlap/us slices from sessions.yaml.
Night is not a VP method. prior_session_hl (MSK desk window) is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import cast

from capitalizator.risk.sessions import Window
from capitalizator.types import require_utc
from capitalizator.zones.model import Bar, ZoneMethod

SESSION_VP_WINDOWS: tuple[str, ...] = ("asia", "europe", "overlap", "us")
MAX_BINS = 5000
# Same 70% Market Profile as card.params.VALUE_AREA_FRAC (bfolkens/py-market-profile).
# Imported as a local constant so zones cannot import card (circular: card → exec → jury → zones).
VALUE_AREA_FRAC = Decimal("0.70")


def method_for(window_name: str) -> ZoneMethod:
    if window_name not in SESSION_VP_WINDOWS:
        raise ValueError(f"session VP window must be one of {SESSION_VP_WINDOWS}")
    return cast(ZoneMethod, f"session_vp_{window_name}")


def last_closed_bounds(window: Window, t: datetime) -> tuple[datetime, datetime] | None:
    """Most recent fully closed occurrence of this UTC window with end < t."""
    when = require_utc(t)
    day = when.date()
    start = datetime.combine(day, window.start, tzinfo=UTC)
    if window.end_is_midnight:
        end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=UTC)
    else:
        end = datetime.combine(day, window.end, tzinfo=UTC)
    if end >= when:
        start -= timedelta(days=1)
        end -= timedelta(days=1)
    if end >= when or end <= start:
        return None
    return start, end


def session_profile(
    bars: Sequence[Bar], *, tick: Decimal
) -> tuple[Decimal, Decimal, Decimal] | None:
    """(poc, vah, val) or None when volume is missing. Not a typical-price bar POC."""
    if tick <= 0:
        raise ValueError("tick must be > 0")
    hist: dict[Decimal, Decimal] = {}
    for bar in bars:
        if bar.volume is None or bar.volume <= 0:
            continue
        bins = _bins(bar.low, bar.high, tick)
        if bins is None:
            continue
        share = bar.volume / Decimal(len(bins))
        for px in bins:
            hist[px] = hist.get(px, Decimal("0")) + share
    if not hist:
        return None
    ordered = sorted(hist.items(), key=lambda row: row[0])
    poc = max(ordered, key=lambda row: row[1])[0]
    vah, val = _value_area(ordered)
    return poc, vah, val


def _bins(low: Decimal, high: Decimal, tick: Decimal) -> list[Decimal] | None:
    lo = (low / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    hi = (high / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    if lo <= 0:
        lo = tick
    if hi < lo:
        hi = lo
    n = int((hi - lo) / tick) + 1
    if n > MAX_BINS:
        return None
    return [lo + tick * i for i in range(n)]


def _value_area(ordered: list[tuple[Decimal, Decimal]]) -> tuple[Decimal, Decimal]:
    total = sum((v for _, v in ordered), Decimal("0"))
    target = total * VALUE_AREA_FRAC
    peak_i = max(range(len(ordered)), key=lambda i: ordered[i][1])
    left = right = peak_i
    acc = ordered[peak_i][1]
    while acc < target and (left > 0 or right < len(ordered) - 1):
        take_left = left > 0
        take_right = right < len(ordered) - 1
        if take_left and take_right:
            if ordered[left - 1][1] >= ordered[right + 1][1]:
                left -= 1
                acc += ordered[left][1]
            else:
                right += 1
                acc += ordered[right][1]
        elif take_left:
            left -= 1
            acc += ordered[left][1]
        else:
            right += 1
            acc += ordered[right][1]
    vah = ordered[right][0]
    val = ordered[left][0]
    return vah, val
