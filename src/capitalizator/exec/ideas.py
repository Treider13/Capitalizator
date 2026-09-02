"""Idea classes and their trade side. One place, no inversion.

Audit finding: `REJECT` (wick beyond the zone, close back inside) and
`FailedBreak.tag` share the same bar condition, so every tradeable bounce was
relabelled `failed_break`, which sat in `_BREAK_IDEAS` and flipped the side —
the desk shorted a support that had just held. The bullish votes (REJECT +1,
DEFEND +1) then produced ACCORD for a short.

Taxonomy now:

  bounce   — close inside the zone, wick did NOT trade through it. Side: with the zone.
  spring   — wick traded through the zone, close back inside (the old
             `failed_break` bar). This IS the held level. Side: with the zone.
             Stop: behind the wick extreme, not behind the zone band.
  breakout — working close beyond the zone. Side: through the zone.
  fade_spring — the old short-against-a-spring. Shadow-only challenger; never sent.
             Kept so the journal can compare both readings on the same bars.

`failed_break` stays accepted as a legacy string (mapped to spring semantics in
the desk); nothing that consumed it is deleted.
"""

from __future__ import annotations

from typing import Literal

from capitalizator.exec.failed_break import FailedBreak
from capitalizator.zones.model import Bar, Zone

Idea = Literal["bounce", "spring", "breakout"]
Side = Literal["buy", "sell"]

SENDABLE_IDEAS: frozenset[str] = frozenset({"bounce", "spring", "breakout"})
CHALLENGER_IDEAS: frozenset[str] = frozenset({"fade_spring"})
LEGACY_ALIASES: dict[str, str] = {"failed_break": "spring"}
# Ideas that trade *through* the zone (side flips). `spring` is deliberately absent.
THROUGH_IDEAS: frozenset[str] = frozenset({"breakout"})


def canonical(idea: str) -> str:
    return LEGACY_ALIASES.get(idea, idea)


def classify(*, zone: Zone, bar: Bar, cav_label: str | None) -> Idea:
    """Closed working bar vs zone → idea class. THROUGH is a breakout; a wick
    through with a close inside is a spring; otherwise a bounce."""
    if cav_label == "THROUGH":
        return "breakout"
    if FailedBreak.tag(zone=zone, bar=bar):
        return "spring"
    return "bounce"


def side_for(idea: str, zone_side: str) -> Side:
    """bounce/spring trade with the zone; breakout trades through it."""
    if zone_side not in {"support", "resistance"}:
        raise ValueError(f"unknown zone side: {zone_side!r}")
    with_zone: Side = "buy" if zone_side == "support" else "sell"
    against: Side = "sell" if zone_side == "support" else "buy"
    kind = canonical(idea)
    if kind in THROUGH_IDEAS:
        return against
    if kind == "fade_spring":
        return against
    if kind in {"bounce", "spring"}:
        return with_zone
    raise ValueError(f"unknown idea: {idea!r}")


def opposite(side: str) -> Side:
    if side == "buy":
        return "sell"
    if side == "sell":
        return "buy"
    raise ValueError(f"unknown side: {side!r}")


def shadow_tag(idea: str) -> str:
    kind = canonical(idea)
    if kind not in SENDABLE_IDEAS:
        raise ValueError(f"not a sendable idea: {idea!r}")
    return kind


def intent_tag(idea: str) -> str:
    """Order tag. Legacy `failed_break_bounce` is still recognised downstream."""
    return shadow_tag(idea)
