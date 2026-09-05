"""1.7.3 / 2.11.4 — first fact is the fastest claim with our frequency.

SILENCE / missing gesture → shadow (no ticket). A printed book gesture with
n<n_min → probe: the fact exists, size is cut, never raised. Mature n → full
fact at size 1. A human first_fact field is not this module: CardDraft forbids
extra keys. Does not open a position.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from capitalizator.stats import n_min

N_MIN = n_min()
PROBE_SIZE = Decimal("0.40")
_HORIZON = re.compile(r"^(\d+)(s|m|h|d)$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class FirstFact:
    tag: str
    first_fact: str | None
    size_mult: Decimal


@dataclass(frozen=True)
class RankedClaim:
    value: str
    horizon: str
    n: int


def resolve(gesture: str | None, n: int) -> FirstFact:
    if n < 0:
        raise ValueError("n must be >= 0")
    if gesture is None or gesture == "SILENCE":
        return FirstFact(tag="shadow_gesture", first_fact=None, size_mult=Decimal("1"))
    if n < N_MIN:
        return FirstFact(tag="probe_gesture", first_fact=gesture, size_mult=PROBE_SIZE)
    return FirstFact(tag="first_fact", first_fact=gesture, size_mult=Decimal("1"))


def horizon_seconds(horizon: str) -> int:
    match = _HORIZON.fullmatch(horizon.strip().lower())
    if match is None:
        raise ValueError(f"horizon must be Ns|Nm|Nh|Nd, got {horizon!r}")
    qty = int(match.group(1))
    if qty <= 0:
        raise ValueError("horizon quantity must be > 0")
    return qty * _UNIT_S[match.group(2)]


def pick_by_horizon(claims: Sequence[RankedClaim]) -> FirstFact:
    """argmin horizon among claims with n≥20. Not a human-typed first_fact."""
    ready: list[RankedClaim] = []
    for claim in claims:
        if claim.n < 0:
            raise ValueError("n must be >= 0")
        if claim.n < N_MIN or claim.value == "SILENCE" or not claim.value.strip():
            continue
        horizon_seconds(claim.horizon)
        ready.append(claim)
    if not ready:
        return FirstFact(tag="shadow_gesture", first_fact=None, size_mult=Decimal("1"))
    best = min(ready, key=lambda c: horizon_seconds(c.horizon))
    return FirstFact(tag="first_fact", first_fact=best.value, size_mult=Decimal("1"))
