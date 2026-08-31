"""5.23 paper — A+ needs five yes and BTC same. F1 cannot raise lev."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.aplus import APlus
from capitalizator.risk.sizing import Sizer


def test_five_roles_and_btc_same_is_aplus() -> None:
    assert APlus.ok(roles=(True, True, True, True, True), btc_same=True) is True


def test_four_roles_is_not_aplus() -> None:
    assert APlus.ok(roles=(True, True, True, True), btc_same=True) is False


def test_btc_against_is_not_aplus() -> None:
    assert APlus.ok(roles=(True, True, True, True, True), btc_same=False) is False


def test_f1_sizer_still_rejects_5x_even_if_aplus() -> None:
    assert APlus.raises_lev_in_f1() is False
    got = Sizer().decide(lev=Decimal("5"), stop_frac=Decimal("0.02"))
    assert got.action == "reject"
