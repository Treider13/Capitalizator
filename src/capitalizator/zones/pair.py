"""Senior level + junior confirmation. Invalidation is the level's own TF.

2025–2026 MTF S/R practice this encodes (not an invention):
  * the higher TF draws the level;
  * the next TF down confirms the reaction (REJECT / THROUGH);
  * the level is dead only when its own TF closes through the band.
A 15m working zone has no junior — the zone itself is the vote.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from capitalizator.patterns.cav import CavLabel, vote
from capitalizator.types import require_utc
from capitalizator.zones.map import HtfBias
from capitalizator.zones.model import Bar, Zone

DEFAULT_LADDER = ("15m", "1h", "4h", "1d")


def junior_tf(tf: str, ladder: Sequence[str] = DEFAULT_LADDER) -> str | None:
    """Next TF down. Working TF has none."""
    order = list(ladder)
    try:
        i = order.index(tf)
    except ValueError:
        return None
    return order[i - 1] if i > 0 else None


def vote_tf(tf: str, ladder: Sequence[str] = DEFAULT_LADDER) -> str:
    """TF whose closed bar votes the pair: junior, or the zone itself on working."""
    return junior_tf(tf, ladder) or tf


def confirm_label(
    zone: Zone,
    bar: Bar,
    *,
    t: datetime,
    htf_bias: HtfBias,
    closed_bars: Sequence[Bar] = (),
    ladder: Sequence[str] = DEFAULT_LADDER,
) -> CavLabel:
    """Junior-TF reaction at a senior level. Wrong TF / unclosed → NOISE."""
    when = require_utc(t)
    if bar.close_ts >= when:
        return "NOISE"
    if bar.symbol != zone.symbol:
        return "NOISE"
    if bar.tf != junior_tf(zone.tf, ladder):
        return "NOISE"
    return vote(zone, bar, t=when, htf_bias=htf_bias, closed_bars=closed_bars)


def pair_ready(
    zone: Zone,
    bars: Sequence[Bar],
    *,
    t: datetime,
    htf_bias: HtfBias,
    ladder: Sequence[str] = DEFAULT_LADDER,
) -> bool:
    """True when the junior TF has REJECT or THROUGH on this level.

    A working-TF zone needs no junior (the 15m CAV is the vote).
    """
    when = require_utc(t)
    if junior_tf(zone.tf, ladder) is None:
        return True
    junior = [
        b
        for b in bars
        if b.symbol == zone.symbol
        and b.tf == junior_tf(zone.tf, ladder)
        and b.close_ts < when
    ]
    if not junior:
        return False
    last = max(junior, key=lambda b: (b.close_ts, b.open_ts))
    cav = confirm_label(
        zone, last, t=when, htf_bias=htf_bias, closed_bars=junior, ladder=ladder
    )
    return cav in {"REJECT", "THROUGH"}


def invalidated(zone: Zone, bars: Sequence[Bar], *, t: datetime) -> bool:
    """Own-TF close through the band after the zone was drawn. Junior closes do not count."""
    when = require_utc(t)
    for bar in bars:
        if bar.symbol != zone.symbol or bar.tf != zone.tf:
            continue
        if bar.close_ts <= zone.created_as_of or bar.close_ts >= when:
            continue
        if zone.side == "support" and bar.close < zone.lo:
            return True
        if zone.side == "resistance" and bar.close > zone.hi:
            return True
    return False
