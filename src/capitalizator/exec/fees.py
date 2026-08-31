"""0.4.7 — VIP0 fees from PHASE-BUILD. Not a live Bybit account lookup.

maker 0.02% = 0.0002, taker 0.055% = 0.00055, times two (open+close), on notional.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

Role = Literal["maker", "taker"]


class FeeTable:
    VIP0_MAKER = Decimal("0.0002")
    VIP0_TAKER = Decimal("0.00055")

    def rate(self, role: Role) -> Decimal:
        if role == "maker":
            return self.VIP0_MAKER
        if role == "taker":
            return self.VIP0_TAKER
        raise ValueError(f"unknown fee role: {role!r}")

    def round_trip(self, notional: Decimal, *, role: Role) -> Decimal:
        if notional <= 0:
            raise ValueError("notional must be > 0")
        return notional * self.rate(role) * 2

    def r_after_fees(self, r_gross: Decimal, notional: Decimal, *, role: Role) -> Decimal:
        return r_gross - self.round_trip(notional, role=role)
