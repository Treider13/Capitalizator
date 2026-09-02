"""Footprint: BUILD from ΔOI, ICEBERG from refills, ABSORB from one-way flow held,
SWEEP from one print; sides by who is building; nothing without the feed."""

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

from capitalizator.oko.footprint import (
    FINGERPRINT_LEN,
    FootprintReport,
    combined_fingerprint,
    needed_side,
    report,
)
from capitalizator.oko.passport import MATURE_N, Passport
from capitalizator.oko.retina import frame
from capitalizator.types import MarketEvent

PRE = make_book(bids=(("100.4", "10"), ("100.3", "10")), asks=(("100.6", "10"), ("100.7", "10")))


def _oi_passport(*, med: str = "0.001", spread: str = "0.0005") -> Passport:
    passport = mature_passport()
    for i in range(MATURE_N):
        sign = 1 if i % 2 else -1
        passport.observe_oi(
            delta_frac=Decimal(med) + Decimal(spread) * sign, level=Decimal("1000000")
        )
    assert passport.oi_delta_frac.mature
    return passport


def _fp(raw, passport=None) -> FootprintReport:
    passport = passport or Passport("BTCUSDT")
    return report(raw, frame(raw, passport))


def test_quiet_window_is_none(clean_window) -> None:
    fp = _fp(clean_window)
    assert fp.label == "NONE"
    assert fp.side is None
    assert fp.votes is False
    assert fp.oi_z is None
    assert fp.liq_rel is None
    assert fp.fingerprint == (0, 0, 3)


def test_needed_side() -> None:
    assert needed_side(idea="bounce", zone_side="support") == "bid"
    assert needed_side(idea="failed_break", zone_side="support") == "bid"
    assert needed_side(idea="breakout", zone_side="support") == "ask"
    assert needed_side(idea="bounce", zone_side="resistance") == "ask"
    assert needed_side(idea="breakout", zone_side="resistance") == "bid"
    with pytest.raises(ValueError):
        needed_side(idea="scalp", zone_side="support")
    with pytest.raises(ValueError):
        needed_side(idea="bounce", zone_side="mid")


def test_oi_jump_up_with_price_up_is_build_long() -> None:
    up = make_book(bids=(("100.6", "10"),), asks=(("100.8", "10"),), seq=2)
    raw = make_window(
        book_pre=PRE,
        path=((T0 + timedelta(seconds=5), up),),
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    fp = _fp(raw, _oi_passport())
    assert fp.label == "BUILD_LONG"
    assert fp.side == "bid"
    assert fp.oi_delta_frac == Decimal("0.01")
    assert fp.oi_z is not None and fp.oi_z > 2
    assert fp.votes is True


def test_oi_jump_up_with_price_down_is_build_short() -> None:
    down = make_book(bids=(("100.2", "10"),), asks=(("100.4", "10"),), seq=2)
    raw = make_window(
        book_pre=PRE,
        path=((T0 + timedelta(seconds=5), down),),
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    fp = _fp(raw, _oi_passport())
    assert fp.label == "BUILD_SHORT"
    assert fp.side == "ask"


def test_still_mid_uses_aggression_for_direction() -> None:
    sells = [make_trade(T0 + timedelta(seconds=1 + i), side="sell", qty="1") for i in range(3)]
    raw = make_window(
        book_pre=PRE,
        trades=sells,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    fp = _fp(raw, _oi_passport())
    assert fp.label == "BUILD_SHORT"  # sellers into support with OI up
    buys = [
        make_trade(T0 + timedelta(seconds=1 + i), side="buy", qty="1", px="100.6") for i in range(3)
    ]
    raw_r = make_window(
        zone=RESISTANCE,
        book_pre=PRE,
        trades=buys,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    assert _fp(raw_r, _oi_passport()).label == "BUILD_LONG"
    no_prints = make_window(
        book_pre=PRE,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    assert _fp(no_prints, _oi_passport()).label == "NONE"  # direction unknown, not guessed


def test_oi_drop_is_unwind_and_small_change_is_nothing() -> None:
    raw = make_window(
        book_pre=PRE,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("990000")),
        ),
    )
    fp = _fp(raw, _oi_passport())
    assert fp.label == "UNWIND"
    assert fp.side is None
    small = make_window(
        book_pre=PRE,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1001000")),
        ),
    )
    assert _fp(small, _oi_passport()).label == "NONE"


def test_oi_without_mature_stat_or_without_a_point_after_t0_is_nothing() -> None:
    raw = make_window(
        book_pre=PRE,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    fp = _fp(raw, mature_passport())
    assert fp.oi_delta_frac == Decimal("0.01")
    assert fp.oi_z is None
    assert fp.label == "NONE"
    only_before = make_window(
        book_pre=PRE, oi_path=((T0 - timedelta(seconds=2), Decimal("1000000")),)
    )
    assert _fp(only_before, _oi_passport()).oi_delta_frac is None


def test_iceberg_refills_under_the_prints() -> None:
    low = make_book(
        bids=(("100.4", "5"), ("100.3", "10")), asks=(("100.6", "10"), ("100.7", "10")), seq=2
    )
    high = PRE.snapshot_copy()
    path = (
        (T0 + timedelta(seconds=1), low),
        (T0 + timedelta(seconds=2), high),
        (T0 + timedelta(seconds=3), low),
        (T0 + timedelta(seconds=4), high),
    )
    prints = [
        make_trade(T0 + timedelta(milliseconds=500 + 1000 * i), px="100.4", qty="5", side="sell")
        for i in range(5)
    ]
    fp = _fp(make_window(book_pre=PRE, path=path, trades=prints))
    assert fp.label == "ICEBERG"
    assert fp.side == "bid"
    assert fp.iceberg_ratio == Decimal("2.5")
    assert fp.iceberg_refills == 2
    # Same prints, one refill only: not an iceberg.
    one = (path[0], path[1], (T0 + timedelta(seconds=3), high))
    assert _fp(make_window(book_pre=PRE, path=one, trades=prints)).label == "NONE"
    # Buy prints do not eat a bid level.
    buys = [
        make_trade(T0 + timedelta(milliseconds=500 + 1000 * i), px="100.4", qty="5", side="buy")
        for i in range(5)
    ]
    assert _fp(make_window(book_pre=PRE, path=path, trades=buys)).label == "NONE"


def test_absorb_needs_mature_passport_flow_and_a_still_book() -> None:
    prints = [
        make_trade(T0 + timedelta(milliseconds=300 + 600 * i), px="100.4", qty="0.6", side="sell")
        for i in range(12)
    ]
    still = make_window(
        book_pre=PRE, path=((T0 + timedelta(seconds=7), PRE.snapshot_copy()),), trades=prints
    )
    assert _fp(still).label == "NONE"  # no passport: volume norm unknown
    fp = _fp(still, mature_passport())
    assert fp.label == "ABSORB"
    assert fp.side == "bid"
    assert fp.taker_volume_rel == Decimal("7.2") / Decimal("2")
    moved = make_book(bids=(("100.1", "10"),), asks=(("100.3", "10"),), seq=2)
    gave_way = make_window(book_pre=PRE, path=((T0 + timedelta(seconds=7), moved),), trades=prints)
    assert _fp(gave_way, mature_passport()).label != "ABSORB"
    thin_end = make_book(
        bids=(("100.4", "2"), ("100.3", "2")), asks=(("100.6", "10"), ("100.7", "10")), seq=2
    )
    collapsed = make_window(
        book_pre=PRE, path=((T0 + timedelta(seconds=7), thin_end),), trades=prints
    )
    assert _fp(collapsed, mature_passport()).label != "ABSORB"
    mixed = prints[:6] + [
        make_trade(
            T0 + timedelta(seconds=5, milliseconds=100 * i), px="100.6", qty="0.6", side="buy"
        )
        for i in range(6)
    ]
    two_way = make_window(
        book_pre=PRE, path=((T0 + timedelta(seconds=7), PRE.snapshot_copy()),), trades=mixed
    )
    assert _fp(two_way, mature_passport()).label == "NONE"


def test_absorb_on_the_ask_side_at_resistance() -> None:
    prints = [
        make_trade(T0 + timedelta(milliseconds=300 + 600 * i), px="100.6", qty="0.6", side="buy")
        for i in range(12)
    ]
    raw = make_window(
        zone=RESISTANCE,
        book_pre=PRE,
        path=((T0 + timedelta(seconds=7), PRE.snapshot_copy()),),
        trades=prints,
    )
    fp = _fp(raw, mature_passport())
    assert fp.label == "ABSORB"
    assert fp.side == "ask"


def test_sweep_by_one_big_print_names_the_aggressor() -> None:
    big = [make_trade(T0 + timedelta(seconds=2), px="100.4", qty="5", side="sell")]
    fp = _fp(make_window(book_pre=PRE, trades=big), mature_passport())
    assert fp.label == "SWEEP"
    assert fp.side == "ask"  # a seller sits on the ask side of the market
    assert fp.votes is False
    buyer = [make_trade(T0 + timedelta(seconds=2), px="100.6", qty="5", side="buy")]
    assert _fp(make_window(book_pre=PRE, trades=buyer), mature_passport()).side == "bid"
    assert _fp(make_window(book_pre=PRE, trades=big)).label == "NONE"  # no passport


def test_sweep_by_range_in_few_prints() -> None:
    fast = [
        make_trade(T0 + timedelta(seconds=1), px="100.4", qty="0.5", side="sell"),
        make_trade(T0 + timedelta(seconds=2), px="99.6", qty="0.5", side="sell"),
    ]
    fp = _fp(make_window(book_pre=PRE, trades=fast), mature_passport())
    assert fp.label == "SWEEP"


def test_liquidations_are_evidence_not_a_label() -> None:
    def liq(ts, qty: str, position: str) -> MarketEvent:
        return MarketEvent(
            stream="liquidation",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=ts,
            recv_ts=ts,
            payload={"px": "100.3", "qty": qty, "position": position},
        )

    rows = [
        liq(T0 + timedelta(seconds=2), "3", "long"),
        liq(T0 + timedelta(seconds=3), "1", "short"),
    ]
    raw = make_window(book_pre=PRE, trades=quiet_prints(), liquidations=rows)
    fp = _fp(raw, mature_passport())
    assert fp.label == "NONE"
    assert fp.liq_dominant == "long"
    assert fp.liq_rel == Decimal("8")  # 4 / median print 0.5
    assert fp.fingerprint[2] == 2
    outside = [liq(T0 + timedelta(seconds=WINDOW_S + 1), "50", "long")]
    fp2 = _fp(make_window(book_pre=PRE, liquidations=outside), mature_passport())
    assert fp2.liq_rel == Decimal("0")
    assert fp2.fingerprint[2] == 0
    assert _fp(make_window(book_pre=PRE, liquidations=rows)).liq_rel is None  # immature → unknown
    with pytest.raises(ValueError, match="liquidation"):
        make_window(book_pre=PRE, liquidations=[make_trade(T0 + timedelta(seconds=1))])


def test_priority_build_over_iceberg_and_fingerprint_shape() -> None:
    low = make_book(
        bids=(("100.4", "5"), ("100.3", "10")), asks=(("100.6", "10"), ("100.7", "10")), seq=2
    )
    high = PRE.snapshot_copy()
    path = (
        (T0 + timedelta(seconds=1), low),
        (T0 + timedelta(seconds=2), high),
        (T0 + timedelta(seconds=3), low),
        (T0 + timedelta(seconds=4), high),
    )
    prints = [
        make_trade(T0 + timedelta(milliseconds=500 + 1000 * i), px="100.4", qty="5", side="sell")
        for i in range(5)
    ]
    raw = make_window(
        book_pre=PRE,
        path=path,
        trades=prints,
        oi_path=(
            (T0 - timedelta(seconds=2), Decimal("1000000")),
            (T0 + timedelta(seconds=4), Decimal("1010000")),
        ),
    )
    fp = _fp(raw, _oi_passport())
    assert fp.label == "BUILD_SHORT"  # OI fact wins over the tape shape; sellers hit the bid
    assert fp.iceberg_ratio == Decimal("2.5")  # still written
    combined = combined_fingerprint(tuple([0] * 10), fp)
    assert len(combined) == FINGERPRINT_LEN == 13
    with pytest.raises(ValueError):
        combined_fingerprint((0, 0), fp)


def test_report_validates() -> None:
    with pytest.raises(ValueError):
        FootprintReport(
            label="UNWIND",
            side="bid",
            oi_delta_frac=None,
            oi_z=None,
            iceberg_ratio=None,
            iceberg_refills=0,
            taker_volume_rel=None,
            liq_rel=None,
            liq_dominant=None,
            fingerprint=(3, 1, 3),
            evidence={},
        )
    with pytest.raises(ValueError):
        FootprintReport(
            label="WHALE",
            side=None,
            oi_delta_frac=None,
            oi_z=None,
            iceberg_ratio=None,
            iceberg_refills=0,
            taker_volume_rel=None,
            liq_rel=None,
            liq_dominant=None,
            fingerprint=(0, 0, 3),
            evidence={},
        )


def test_two_runs_same_footprint() -> None:
    def run():
        raw = make_window(
            book_pre=PRE,
            trades=quiet_prints(),
            oi_path=(
                (T0 - timedelta(seconds=2), Decimal("1000000")),
                (T0 + timedelta(seconds=4), Decimal("1010000")),
            ),
        )
        return _fp(raw, _oi_passport())

    assert run() == run()


def test_spring_is_the_bounce_family() -> None:
    """main renamed failed_break → spring (traded WITH the zone). ОКО must accept it."""
    from capitalizator.oko.forecast import class_key
    from capitalizator.oko.memory import is_trap, needed_outcome

    assert needed_side(idea="spring", zone_side="support") == "bid"
    assert needed_side(idea="spring", zone_side="resistance") == "ask"
    assert needed_outcome("spring") == "bounce"
    assert is_trap(idea="spring", outcome="break") is True
    assert class_key(
        idea="spring", cav="REJECT", zlg="DEFEND", regime="RANGE", footprint="NONE"
    ).startswith("spring ×")
