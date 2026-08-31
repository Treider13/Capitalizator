"""VIP0 round-trip fees cut +1R by a known amount. Fill is a print, not close."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.exec.fees import FeeTable
from capitalizator.exec.fill_model import NaiveQueueFill


def test_maker_round_trip_on_known_notional() -> None:
    fees = FeeTable()
    notional = Decimal("10000")
    assert fees.round_trip(notional, role="maker") == Decimal("4")
    assert fees.r_after_fees(Decimal("100"), notional, role="maker") == Decimal("96")


def test_taker_round_trip_on_known_notional() -> None:
    fees = FeeTable()
    notional = Decimal("10000")
    assert fees.round_trip(notional, role="taker") == Decimal("11")
    assert fees.r_after_fees(Decimal("100"), notional, role="taker") == Decimal("89")


def test_plus_one_r_after_fees_is_strictly_smaller() -> None:
    fees = FeeTable()
    gross = Decimal("100")
    after = fees.r_after_fees(gross, Decimal("10000"), role="maker")
    assert after < gross
    assert gross - after == Decimal("4")


def test_buy_limit_fills_on_print_through_not_on_higher_print() -> None:
    q = NaiveQueueFill()
    assert q.fills(side="buy", limit_px=Decimal("100"), prints=[Decimal("100")]) is True
    assert q.fills(side="buy", limit_px=Decimal("100"), prints=[Decimal("100.1")]) is False


def test_sell_limit_fills_on_print_through() -> None:
    q = NaiveQueueFill()
    assert q.fills(side="sell", limit_px=Decimal("100"), prints=[Decimal("100")]) is True
    assert q.fills(side="sell", limit_px=Decimal("100"), prints=[Decimal("99.9")]) is False
