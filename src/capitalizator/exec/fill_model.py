"""Naive queue: a limit fills if a print crosses it. Not bar close."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

Side = Literal["buy", "sell"]


class NaiveQueueFill:
    def fills(self, *, side: Side, limit_px: Decimal, prints: Sequence[Decimal]) -> bool:
        if limit_px <= 0:
            raise ValueError("limit_px must be > 0")
        if side == "buy":
            return any(px <= limit_px for px in prints)
        if side == "sell":
            return any(px >= limit_px for px in prints)
        raise ValueError(f"unknown side: {side!r}")
