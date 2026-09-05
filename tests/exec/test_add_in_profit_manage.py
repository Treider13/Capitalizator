"""Live manage may add only through ProfitAdd. average_in stays dead."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.exec.manage import TradeManager
from capitalizator.hyexec.pyramid import ProfitAdd, ProfitAddError
from capitalizator.risk.schema import reject_forbidden_keys


def test_average_in_still_unrepresentable() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        reject_forbidden_keys({"action": "average_in"})


def test_manager_rejects_add_below_long_entry() -> None:
    with pytest.raises(ProfitAddError, match="above entry"):
        TradeManager().add_in_profit(
            side="buy",
            entry=Decimal("100"),
            add_price=Decimal("99"),
            extra_risk=Decimal("0.005"),
            open_risk=Decimal("0.01"),
        )


def test_manager_add_in_profit_is_the_only_add() -> None:
    got = TradeManager().add_in_profit(
        side="buy",
        entry=Decimal("100"),
        add_price=Decimal("101"),
        extra_risk=Decimal("0.005"),
        open_risk=Decimal("0.01"),
    )
    assert isinstance(got, ProfitAdd)
    assert got.action == "add_in_profit"
    assert got.total_risk == Decimal("0.015")
