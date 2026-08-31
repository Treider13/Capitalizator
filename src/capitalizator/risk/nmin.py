"""4.18.5 paper — F4 may quarter size when n<20 or SILENCE. F1 does not.

F1 law: size_mult stays 1. This module does not raise size.
"""

from __future__ import annotations

from decimal import Decimal

N_MIN = 20
QUARTER = Decimal("0.25")


def size_mult(*, n: int, gesture: str | None, phase: str = "f1") -> Decimal:
    if n < 0:
        raise ValueError("n must be >= 0")
    if phase == "f1":
        return Decimal("1")
    if gesture == "SILENCE" or n < N_MIN:
        return QUARTER
    return Decimal("1")
