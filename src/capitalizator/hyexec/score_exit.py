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
    expand: bool = False,
    structure_ok: bool = False,
) -> Action:
    if drop < 0:
        raise ValueError("drop must be >= 0")
    # EXPAND: the model is noise next to a live book/structure. Score may
    # flatten only after the structure is already dead, or when FLOOR is on.
    if expand and structure_ok:
        return "hold"
    if score_now <= score_entry - drop:
        return "flatten"
    return "hold"
