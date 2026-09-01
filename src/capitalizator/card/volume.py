"""Session volume profile for contour B. Not a ZLG voice. Does not open size."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.card.live import VolumeSnapshot
from capitalizator.card.params import VALUE_AREA_FRAC
from capitalizator.zones.model import Bar

# Alias kept for callers; 70% Market Profile (not 68% 1σ).
VALUE_FRAC = VALUE_AREA_FRAC


def snapshot(
    bars: Sequence[Bar],
    *,
    walls: str | None = None,
    eaten_levels: str | None = None,
) -> VolumeSnapshot:
    if not bars:
        return VolumeSnapshot(walls=walls, eaten_levels=eaten_levels)
    last = bars[-1]
    vols = [b.volume if b.volume and b.volume > 0 else Decimal("1") for b in bars]
    total = sum(vols, Decimal("0"))
    typical = [((b.high + b.low + b.close) / 3, v) for b, v in zip(bars, vols, strict=True)]
    vwap = sum((px * v for px, v in typical), Decimal("0")) / total if total else last.close
    poc_px, _ = max(typical, key=lambda row: row[1])
    ordered = sorted(typical, key=lambda row: row[0])
    vah, val = _value_area(ordered, total)
    signed = Decimal("0")
    for bar, vol in zip(bars, vols, strict=True):
        if bar.close > bar.open:
            signed += vol
        elif bar.close < bar.open:
            signed -= vol
    prior = vols[:-1]
    mean = (sum(prior, Decimal("0")) / len(prior)) if prior else vols[-1]
    rvol = (vols[-1] / mean) if mean > 0 else Decimal("0")
    return VolumeSnapshot(
        poc=_n(poc_px),
        vah=_n(vah),
        val=_n(val),
        vwap=_n(vwap),
        delta=_n(signed),
        rvol=_n(rvol),
        eaten_levels=eaten_levels,
        walls=walls,
        a_price=_n(last.close),
        a_volume=_n(vols[-1]),
        a_delta=_n(signed),
        a_wall=walls,
    )


def _value_area(
    ordered: list[tuple[Decimal, Decimal]], total: Decimal
) -> tuple[Decimal, Decimal]:
    if not ordered:
        return Decimal("0"), Decimal("0")
    target = total * VALUE_FRAC
    acc = Decimal("0")
    lo = ordered[0][0]
    hi = ordered[-1][0]
    # Grow from POC (max vol) outward by price neighbors.
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
    lo = ordered[left][0]
    hi = ordered[right][0]
    return hi, lo


def _n(value: Decimal) -> str:
    return format(value.normalize(), "f")
