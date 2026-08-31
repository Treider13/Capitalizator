"""Dead K-line quality and gap segments. Journal, not an entry.

15m working-TF thresholds are constants (not registry.yaml).
stagnant / illiquid → CAV NOISE. A jump gap only splits the ATR window.
Does not open size.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal

from capitalizator.types import require_utc
from capitalizator.zones.model import Bar

BarQuality = Literal["live", "stagnant", "illiquid"]

LIVE: BarQuality = "live"
STAGNANT: BarQuality = "stagnant"
ILLIQUID: BarQuality = "illiquid"
QUALITY_LABELS = frozenset({LIVE, STAGNANT, ILLIQUID})

# Working TF is 15m. Other TFs use the same constants until a later contour measures them.
JUMP_RATIO_15M = Decimal("0.15")
ILLIQUID_ZERO_BARS = 2
STAGNANT_SAME_CLOSES = 5
ATR_N = 14


def split_on_gaps(
    bars: Sequence[Bar],
    *,
    jump_ratio: Decimal = JUMP_RATIO_15M,
) -> list[list[Bar]]:
    """Split a same-symbol same-tf series on |open − prev.close| / prev.close > jump.

    A gap is a segment break for ATR / w_now. It is not a quality label and not NOISE.
    """
    if jump_ratio <= 0:
        raise ValueError("jump_ratio must be > 0")
    ordered = sorted(bars, key=lambda b: (b.close_ts, b.open_ts))
    if not ordered:
        return []
    segments: list[list[Bar]] = [[ordered[0]]]
    prev = ordered[0]
    for bar in ordered[1:]:
        if _is_gap(prev, bar, jump_ratio):
            segments.append([bar])
        else:
            segments[-1].append(bar)
        prev = bar
    return segments


def prior_same_tf(history: Sequence[Bar], current: Bar, *, t: datetime) -> list[Bar]:
    """Closed bars of the same symbol/tf that closed before both `current` and `t`."""
    when = require_utc(t)
    priors = [
        b
        for b in history
        if b.symbol == current.symbol
        and b.tf == current.tf
        and b.close_ts < current.close_ts
        and b.close_ts < when
    ]
    priors.sort(key=lambda b: (b.close_ts, b.open_ts))
    return priors


def last_gap_segment(history: Sequence[Bar], current: Bar, *, t: datetime) -> list[Bar]:
    """Priors after the last jump. Empty if there is no usable history."""
    segs = split_on_gaps(prior_same_tf(history, current, t=t))
    return segs[-1] if segs else []


def atr(bars: Sequence[Bar], n: int = ATR_N) -> Decimal | None:
    """Mean true range over the last n steps (same formula CAV already used). Needs n+1 bars."""
    if n <= 0:
        raise ValueError("atr n must be > 0")
    if len(bars) < n + 1:
        return None
    window = bars[-(n + 1) :]
    total = Decimal("0")
    prev = window[0]
    for bar in window[1:]:
        tr = max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        total += tr
        prev = bar
    return total / n


def classify_bar_quality(
    history: Sequence[Bar],
    current: Bar,
    *,
    t: datetime,
) -> BarQuality:
    """live | stagnant | illiquid. volume=None skips the illiquid check (do not invent)."""
    require_utc(t)
    require_utc(current.close_ts)
    series = prior_same_tf(history, current, t=t) + [current]
    if len(series) >= STAGNANT_SAME_CLOSES:
        last = series[-STAGNANT_SAME_CLOSES:]
        if all(b.close == last[0].close for b in last):
            return STAGNANT
    if current.volume is not None and len(series) >= ILLIQUID_ZERO_BARS:
        last = series[-ILLIQUID_ZERO_BARS:]
        if all(b.volume is not None and b.volume == 0 for b in last):
            return ILLIQUID
    return LIVE


def _is_gap(prev: Bar, bar: Bar, jump_ratio: Decimal) -> bool:
    if prev.close <= 0:
        return True
    return abs(bar.open - prev.close) / prev.close > jump_ratio
