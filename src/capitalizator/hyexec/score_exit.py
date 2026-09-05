"""Score drop flattens the remainder. Adding size is not a representable action."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

Action = Literal["flatten", "hold"]


def remainder_action(
    *,
    score_now: Decimal,
    score_entry: Decimal,
    drop: Decimal,
) -> Action:
    if drop < 0:
        raise ValueError("drop must be >= 0")
    if score_now <= score_entry - drop:
        return "flatten"
    return "hold"
