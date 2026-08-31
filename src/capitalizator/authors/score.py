"""2.12.3 — weight from our hits, not likes. 1 call is not a guru.

n < 5 → weight 0. Bayes-style shrink: n/(n+κ) × hit rate, κ=20.
Never returns accept. Does not open size.
"""

from __future__ import annotations

from decimal import Decimal

N_MIN = 5
KAPPA = Decimal("20")


def weight(hits: int, n: int, *, kappa: Decimal = KAPPA) -> Decimal:
    if n < 0 or hits < 0 or hits > n:
        raise ValueError("hits/n out of range")
    if kappa <= 0:
        raise ValueError("kappa must be > 0")
    if n < N_MIN:
        return Decimal("0")
    return (Decimal(n) / (Decimal(n) + kappa)) * (Decimal(hits) / Decimal(n))


def author_accepts(*, has_zone: bool) -> bool:
    """Author voice is never accept. No zone → no entry."""
    if not has_zone:
        return False
    return False
