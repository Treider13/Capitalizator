"""Channel weights from our journal. They never open size.

INVENTION-JURY: n<20 → weights equal, accord still required.
After an exam: w = n/(n+κ) × hit. κ is large at start (same 20 as n_min).
Weight ranks already-agreed classes. It is not a vote that creates ACCORD.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

KAPPA = Decimal("20")
N_MIN = 20


def channel_weight(n: int, hit: Decimal, *, kappa: Decimal = KAPPA) -> Decimal:
    if n < 0:
        raise ValueError("n must be >= 0")
    if hit < 0 or hit > 1:
        raise ValueError("hit must be in [0, 1]")
    if kappa <= 0:
        raise ValueError("kappa must be > 0")
    return (Decimal(n) / (Decimal(n) + kappa)) * hit


def rank_weight(
    n: int,
    hit: Decimal,
    *,
    exam_done: bool = False,
    kappa: Decimal = KAPPA,
) -> Decimal:
    """Equal before exam / n<20. Formula only ranks after that."""
    if not exam_done or n < N_MIN:
        return Decimal("1")
    return channel_weight(n, hit, kappa=kappa)


def equal_before_exam(ns: Sequence[int]) -> bool:
    return all(n < N_MIN for n in ns)


def weight_opens_size(_weight: Decimal) -> bool:
    return False
