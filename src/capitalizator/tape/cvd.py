"""Signed tape in the same window as the touch.

CVD = sum(+qty on buy, −qty on sell). This is a fact, not a 5-minute signal
and not a size opener. Unknown taker side is an error (we do not invent it).
Non-trade streams are skipped — they are not prints.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent


class CVD:
    def window(self, trades: Sequence[MarketEvent]) -> Decimal:
        clf = TapeClassifier()
        total = Decimal("0")
        for trade in trades:
            if trade.stream != "trades":
                continue
            side = clf.taker_side(trade)
            qty = Decimal(str(trade.payload.get("qty") or "0"))
            if qty <= 0:
                raise ValueError("cvd qty must be > 0")
            total += qty if side == "buy" else -qty
        return total
