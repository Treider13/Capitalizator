"""Retina: dimensionless facts; None where the fact does not exist; PIT passport."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from tests.oko.conftest import (
    RESISTANCE,
    T0,
    WINDOW_S,
    make_book,
    make_trade,
    make_window,
    mature_passport,
    quiet_prints,
)

from capitalizator.oko.passport import Passport
from capitalizator.oko.retina import RawWindow, frame, observe_passport


def test_sell_into_support_is_pressure() -> None:
    trades = [
        make_trade(T0 + timedelta(seconds=1), side="sell", qty="3"),
        make_trade(T0 + timedelta(seconds=2), side="buy", qty="1"),
    ]
    fr = frame(make_window(trades=trades), Passport("BTCUSDT"))
    assert fr.n_prints == 2
    assert fr.pressure_qty == Decimal("3")
    assert fr.relief_qty == Decimal("1")
    assert fr.aggression == Decimal("0.5")
    assert fr.prints_per_s == Decimal("2") / Decimal(WINDOW_S)


def test_buy_into_resistance_is_pressure() -> None:
    trades = [make_trade(T0 + timedelta(seconds=1), side="buy", qty="2", px="100.6")]
    fr = frame(make_window(zone=RESISTANCE, trades=trades), Passport("BTCUSDT"))
    assert fr.pressure_qty == Decimal("2")
    assert fr.relief_qty == Decimal("0")
    assert fr.aggression == Decimal("1")


def test_no_prints_gives_none_not_zero_aggression() -> None:
    fr = frame(make_window(), Passport("BTCUSDT"))
    assert fr.n_prints == 0
    assert fr.aggression is None
    assert fr.range_ticks is None
    assert fr.max_print_qty is None


def test_depth_spread_and_end_ratio() -> None:
    pre = make_book(bids=(("100.4", "10"), ("100.3", "10")), asks=(("100.6", "5"),))
    end = make_book(bids=(("100.4", "2"), ("100.3", "3")), asks=(("100.6", "5"),), seq=2)
    fr = frame(
        make_window(book_pre=pre, path=((T0 + timedelta(seconds=4), end),)), Passport("BTCUSDT")
    )
    assert fr.depth_side_pre == Decimal("20")
    assert fr.depth_opp_pre == Decimal("5")
    assert fr.depth_side_end == Decimal("5")
    assert fr.depth_end_ratio == Decimal("0.25")
    assert fr.spread_ticks_pre == Decimal("2")
    assert fr.imbalance_pre == Decimal("15") / Decimal("25")
    assert fr.mid_move_ticks == Decimal("0")


def test_ofi_needs_two_books_and_is_scaled_by_depth() -> None:
    pre = make_book(bids=(("100.4", "10"),), asks=(("100.6", "10"),))
    later = make_book(bids=(("100.4", "15"),), asks=(("100.6", "10"),), seq=2)
    one = frame(
        make_window(book_pre=pre, path=((T0 + timedelta(seconds=2), later),)), Passport("BTCUSDT")
    )
    assert one.ofi is None
    two = frame(
        make_window(
            book_pre=pre,
            path=(
                (T0 + timedelta(seconds=1), pre.snapshot_copy()),
                (T0 + timedelta(seconds=2), later),
            ),
        ),
        Passport("BTCUSDT"),
    )
    assert two.ofi == Decimal("5")
    assert two.ofi_rel == Decimal("0.5")


def test_normalised_fields_none_until_passport_mature() -> None:
    fr = frame(make_window(trades=quiet_prints()), Passport("BTCUSDT"))
    assert fr.passport_mature is False
    assert fr.depth_side_rel is None
    assert fr.rate_rel is None
    assert fr.range_rel is None
    assert fr.spread_z is None
    mature = frame(make_window(trades=quiet_prints()), mature_passport())
    assert mature.passport_mature is True
    assert mature.depth_side_rel == Decimal("1")
    assert mature.rate_rel == Decimal("0.5") / Decimal("0.5")
    assert mature.range_rel == Decimal("2") / Decimal("2")
    assert mature.spread_z == Decimal("0")


def test_observe_passport_is_after_the_frame() -> None:
    """The window that made the passport mature is judged immature — PIT."""
    passport = Passport("BTCUSDT")
    for _ in range(29):
        raw = make_window(trades=quiet_prints())
        observe_passport(raw, passport, frame(raw, passport))
    raw = make_window(trades=quiet_prints())
    fr = frame(raw, passport)
    assert fr.passport_mature is False
    observe_passport(raw, passport, fr)
    assert passport.mature is True
    assert passport.print_qty.n == 30 * 4


def test_window_rejects_bad_inputs() -> None:
    from capitalizator.book.reconstruct import Book

    with pytest.raises(ValueError, match="ready"):
        make_window(book_pre=Book(tick_size="0.1"))
    pre = make_book()
    with pytest.raises(ValueError, match="time-ordered"):
        make_window(
            book_pre=pre,
            path=((T0 + timedelta(seconds=3), pre), (T0 + timedelta(seconds=1), pre)),
        )
    with pytest.raises(ValueError, match="symbol"):
        frame(make_window(), Passport("ETHUSDT"))
    with pytest.raises(ValueError):
        RawWindow(
            symbol="BTCUSDT",
            zone=make_window().zone,
            t0=T0,
            window_s=0,
            tick_size=Decimal("0.1"),
            delta_ticks=5,
            book_pre=pre,
            book_path=(),
            trades=(),
            adds=(),
            wall_events=(),
        )


def test_prints_outside_window_and_other_streams_are_ignored() -> None:
    late = make_trade(T0 + timedelta(seconds=WINDOW_S + 1), qty="50")
    early = make_trade(T0 - timedelta(seconds=1), qty="50")
    inside = make_trade(T0 + timedelta(seconds=1), qty="1")
    fr = frame(make_window(trades=[late, early, inside]), Passport("BTCUSDT"))
    assert fr.n_prints == 1
    assert fr.max_print_qty == Decimal("1")


def test_oi_liquidation_and_funding_facts() -> None:
    from capitalizator.types import MarketEvent

    liq = MarketEvent(
        stream="liquidation",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=T0 + timedelta(seconds=2),
        recv_ts=T0 + timedelta(seconds=2),
        payload={"px": "100.3", "qty": "2", "position": "short"},
    )
    raw = make_window(
        trades=quiet_prints(),
        oi_path=(
            (T0 - timedelta(seconds=5), Decimal("1000")),
            (T0, Decimal("1001")),
            (T0 + timedelta(seconds=3), Decimal("1005")),
            (T0 + timedelta(seconds=WINDOW_S + 1), Decimal("2000")),
        ),
        liquidations=[liq],
        funding=Decimal("0.0003"),
    )
    fr = frame(raw, Passport("BTCUSDT"))
    assert (fr.oi_before, fr.oi_after) == (Decimal("1001"), Decimal("1005"))
    assert fr.oi_delta_frac == Decimal("4") / Decimal("1001")
    assert fr.oi_z is None  # stat immature
    assert fr.liq_short_qty == Decimal("2") and fr.liq_long_qty == Decimal("0")
    assert fr.liq_rel is None and fr.taker_volume_rel is None
    assert fr.funding == Decimal("0.0003")
    mature = frame(raw, mature_passport())
    assert mature.liq_rel == Decimal("4")
    assert mature.taker_volume_rel == Decimal("2.6") / Decimal("2")
    passport = Passport("BTCUSDT")
    observe_passport(raw, passport, fr)
    assert passport.oi_delta_frac.n == 1 and passport.oi_level.n == 1 and passport.funding.n == 1
    none = frame(make_window(), Passport("BTCUSDT"))
    assert none.oi_delta_frac is None and none.funding is None
    with pytest.raises(ValueError, match="oi"):
        make_window(oi_path=((T0, Decimal("0")),))
    with pytest.raises(ValueError, match="time-ordered"):
        make_window(oi_path=((T0 + timedelta(seconds=1), Decimal("1")), (T0, Decimal("1"))))
