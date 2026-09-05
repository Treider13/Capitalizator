"""Pyramid only above the entry. average_in stays unrepresentable."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.hyexec.pyramid import ProfitAdd, ProfitAddError
from capitalizator.risk.schema import reject_forbidden_keys


def test_average_in_still_forbidden() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        reject_forbidden_keys({"average_in": True})
    with pytest.raises(ValueError, match="forbidden"):
        reject_forbidden_keys({"action": "pyramid"})
    with pytest.raises(ValueError, match="forbidden"):
        reject_forbidden_keys({"action": "add_to_position"})


def test_add_in_profit_long_below_entry_dies() -> None:
    with pytest.raises(ProfitAddError, match="above entry"):
        ProfitAdd(
            side="buy",
            entry=Decimal("100"),
            add_price=Decimal("99"),
            extra_risk=Decimal("0.01"),
            open_risk=Decimal("0.01"),
        )


def test_add_in_profit_short_above_entry_dies() -> None:
    with pytest.raises(ProfitAddError, match="below entry"):
        ProfitAdd(
            side="sell",
            entry=Decimal("100"),
            add_price=Decimal("101"),
            extra_risk=Decimal("0.01"),
            open_risk=Decimal("0.01"),
        )


def test_add_in_profit_long_above_entry_ok() -> None:
    got = ProfitAdd(
        side="buy",
        entry=Decimal("100"),
        add_price=Decimal("101.5"),
        extra_risk=Decimal("0.01"),
        open_risk=Decimal("0.01"),
    )
    assert got.action == "add_in_profit"
    assert got.total_risk == Decimal("0.02")


def test_total_risk_cannot_exceed_two_percent() -> None:
    with pytest.raises(ProfitAddError, match="2"):
        ProfitAdd(
            side="buy",
            entry=Decimal("100"),
            add_price=Decimal("102"),
            extra_risk=Decimal("0.015"),
            open_risk=Decimal("0.01"),
        )
