"""1.7.3 — first fact is a gesture with n≥20. SILENCE / n<20 → shadow, no sizeup.

Does not open a position. Does not map DEFEND to more lots.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

N_MIN = 20


@dataclass(frozen=True)
class FirstFact:
    tag: str
    first_fact: str | None
    size_mult: Decimal


def resolve(gesture: str | None, n: int) -> FirstFact:
    if n < 0:
        raise ValueError("n must be >= 0")
    if gesture is None or gesture == "SILENCE" or n < N_MIN:
        return FirstFact(tag="shadow_gesture", first_fact=None, size_mult=Decimal("1"))
    return FirstFact(tag="first_fact", first_fact=gesture, size_mult=Decimal("1"))
