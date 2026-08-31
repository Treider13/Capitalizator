"""1.6.3 — 50% off at +1R. Remainder trails structure. No mechanical BE at +2%.

Does not place an order. Does not add size. No mechanical break-even percent knob.
"""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.schema import ManageIntent

HALF = Decimal("0.5")


class TradeManager:
    def __init__(self) -> None:
        self.reduced_at_1r = False
        self.remaining = Decimal("1")

    def on_fill(
        self,
        *,
        side: str,
        entry: Decimal,
        stop: Decimal,
        fill_px: Decimal,
    ) -> ManageIntent | None:
        r = abs(entry - stop)
        if r <= 0:
            raise ValueError("R must be > 0")
        moved = (fill_px - entry) if side == "buy" else (entry - fill_px)
        if moved <= -r:
            self.remaining = Decimal("0")
            return ManageIntent(action="flatten")
        if not self.reduced_at_1r and moved >= r:
            self.reduced_at_1r = True
            self.remaining = HALF
            return ManageIntent(action="reduce", fraction=HALF)
        return None

    def trail_stop(self, last_swing: Decimal) -> Decimal:
        """New stop is the last broken swing / zone, not the entry."""
        if last_swing <= 0:
            raise ValueError("last_swing must be > 0")
        return last_swing
