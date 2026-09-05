"""Add only in profit. average_in / pyramid-down remain unrepresentable."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

MAX_TOTAL_RISK = Decimal("0.02")


class ProfitAddError(ValueError):
    """The add is not above (long) / below (short) the live entry, or risk blows the cap."""


@dataclass(frozen=True)
class ProfitAdd:
    side: Literal["buy", "sell"]
    entry: Decimal
    add_price: Decimal
    extra_risk: Decimal
    open_risk: Decimal
    action: str = "add_in_profit"

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ProfitAddError("side must be buy|sell")
        if self.entry <= 0 or self.add_price <= 0:
            raise ProfitAddError("prices must be > 0")
        if self.extra_risk <= 0 or self.open_risk <= 0:
            raise ProfitAddError("risk legs must be > 0")
        if self.side == "buy" and self.add_price <= self.entry:
            raise ProfitAddError("long add must be above entry")
        if self.side == "sell" and self.add_price >= self.entry:
            raise ProfitAddError("short add must be below entry")
        if self.total_risk > MAX_TOTAL_RISK:
            raise ProfitAddError("total risk cannot exceed 2%")

    @property
    def total_risk(self) -> Decimal:
        return self.open_risk + self.extra_risk
