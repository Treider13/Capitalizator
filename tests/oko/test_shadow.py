"""Shadow: a wall that vanished without prints is a spoof; one eaten is not."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from tests.oko.conftest import (
    T0,
    WINDOW_S,
    make_book,
    make_trade,
    make_window,
    mature_passport,
    quiet_prints,
)

from capitalizator.book.wall_watch import WallEvent
from capitalizator.oko.passport import Passport
from capitalizator.oko.retina import frame
from capitalizator.oko.shadow import FINGERPRINT_LEN, report
from capitalizator.zlg.gesture import BookAdd

PRE = make_book(bids=(("100.4", "10"), ("100.3", "10")), asks=(("100.6", "10"), ("100.7", "10")))


def _stacked(levels: dict[str, str], side: str = "bid", seq: int = 2):
    bids = dict((("100.4", "10"), ("100.3", "10")))
    asks = dict((("100.6", "10"), ("100.7", "10")))
    target = bids if side == "bid" else asks
    for px, qty in levels.items():
        target[px] = str(Decimal(target.get(px, "0")) + Decimal(qty))
    return make_book(bids=tuple(bids.items()), asks=tuple(asks.items()), seq=seq)


def _vanishing_window(levels: dict[str, str], *, side: str = "bid", trades=(), walls=()):
    t_add = T0 + timedelta(seconds=1)
    t_pull = T0 + timedelta(seconds=3)
    path = (
        (t_add, _stacked(levels, side)),
        (t_pull, PRE.snapshot_copy()),
        (T0 + timedelta(seconds=WINDOW_S), PRE.snapshot_copy()),
    )
    adds = tuple(
        BookAdd(ts=t_add, side=side, px=Decimal(px), qty=Decimal(qty))  # type: ignore[arg-type]
        for px, qty in levels.items()
    )
    return make_window(book_pre=PRE, path=path, trades=trades, adds=adds, walls=walls)


def _shadow(raw, passport: Passport | None = None):
    passport = passport or Passport("BTCUSDT")
    return report(raw, frame(raw, passport))


def test_clean_window_is_clean(clean_window) -> None:
    sh = _shadow(clean_window)
    assert sh.label == "CLEAN"
    assert sh.book_trust == 1.0
    assert sh.spoof_score == 0.0
    assert sh.layering_score == 0.0
    assert sh.cascade is False
    assert sh.tape_trust is None  # 4 prints: no evidence, not trust


def test_zone_side_wall_that_vanishes_is_spoof() -> None:
    sh = _shadow(_vanishing_window({"100.4": "40"}))
    assert sh.label == "SPOOF"
    assert sh.spoof_side == "zone"
    assert sh.spoof_score == 1.0
    assert sh.book_trust == 0.0
    assert sh.evidence["zone_vanished"] == "40"


def test_wall_eaten_by_prints_is_not_spoof() -> None:
    eaten = [
        make_trade(T0 + timedelta(seconds=2), px="100.4", qty="20", side="sell"),
        make_trade(T0 + timedelta(seconds=2, milliseconds=500), px="100.4", qty="20", side="sell"),
    ]
    sh = _shadow(_vanishing_window({"100.4": "40"}, trades=eaten))
    assert sh.label == "CLEAN"
    assert sh.spoof_score == 0.0
    assert sh.book_trust == 1.0


def test_buy_prints_do_not_eat_a_bid_wall() -> None:
    wrong_side = [make_trade(T0 + timedelta(seconds=2), px="100.4", qty="40", side="buy")]
    sh = _shadow(_vanishing_window({"100.4": "40"}, trades=wrong_side))
    assert sh.label == "SPOOF"


def test_small_add_is_not_a_wall() -> None:
    sh = _shadow(_vanishing_window({"100.4": "1"}))
    assert sh.label == "CLEAN"
    assert sh.spoof_score == 0.0


def test_opposite_side_spoof_halves_trust() -> None:
    sh = _shadow(_vanishing_window({"100.6": "20"}, side="ask"))
    assert sh.label == "SPOOF"
    assert sh.spoof_side == "opp"
    assert sh.opp_spoof_score == 1.0
    assert sh.book_trust == 0.5


def test_four_vanishing_levels_are_layering() -> None:
    sh = _shadow(_vanishing_window({"100.4": "10", "100.3": "10", "100.2": "10", "100.1": "10"}))
    assert sh.label == "LAYERING"
    assert sh.layered_levels == 4
    assert sh.layering_score == 1.0
    assert sh.book_trust == 0.0
    assert sh.flicker_n == 4  # half-life 2s ≤ FLICKER_S


def test_two_vanishing_levels_are_spoof_not_layering() -> None:
    sh = _shadow(_vanishing_window({"100.4": "20", "100.3": "20"}))
    assert sh.label == "SPOOF"
    assert sh.layering_score == 0.0


def test_wall_watch_pull_is_a_second_witness() -> None:
    pulled = WallEvent(
        symbol="BTCUSDT",
        px="100.4",
        side="bid",
        size=Decimal("10"),
        kind="pulled",
        ts=T0 + timedelta(seconds=2),
    )
    sh = _shadow(make_window(book_pre=PRE, walls=[pulled]))
    assert sh.label == "SPOOF"
    assert sh.spoof_score == 1.0
    eaten = WallEvent(
        symbol="BTCUSDT",
        px="100.3",
        side="bid",
        size=Decimal("10"),
        kind="eaten",
        ts=T0 + timedelta(seconds=2),
    )
    mixed = _shadow(make_window(book_pre=PRE, walls=[pulled, eaten]))
    assert mixed.label == "CLEAN"
    assert mixed.spoof_score == 0.5
    assert mixed.book_trust == 0.5


def test_pull_before_the_window_clock_is_ignored() -> None:
    old = WallEvent(
        symbol="BTCUSDT",
        px="100.4",
        side="bid",
        size=Decimal("50"),
        kind="pulled",
        ts=T0 - timedelta(seconds=WINDOW_S + 1),
    )
    assert _shadow(make_window(book_pre=PRE, walls=[old])).label == "CLEAN"


def test_cascade_needs_mature_passport_and_all_four_signs() -> None:
    prints = [
        make_trade(
            T0 + timedelta(milliseconds=150 * (i + 1)),
            px=str(Decimal("100.4") - Decimal("0.1") * (i // 4)),
            qty="1",
            side="sell",
        )
        for i in range(40)
    ]
    collapsed = make_book(
        bids=(("100.4", "2"), ("100.3", "2")), asks=(("100.6", "10"), ("100.7", "10")), seq=3
    )
    raw = make_window(book_pre=PRE, path=((T0 + timedelta(seconds=7), collapsed),), trades=prints)
    immature = _shadow(raw)
    assert immature.cascade is False
    assert immature.label == "CLEAN"
    sh = _shadow(raw, mature_passport())
    assert sh.cascade is True
    assert sh.label == "CASCADE"
    assert sh.book_trust == 0.0
    # Same prints but depth held: not a cascade.
    held = make_window(
        book_pre=PRE, path=((T0 + timedelta(seconds=7), PRE.snapshot_copy()),), trades=prints
    )
    assert _shadow(held, mature_passport()).cascade is False


def test_thin_book_vs_passport() -> None:
    thin_pre = make_book(bids=(("100.4", "2"), ("100.3", "2")), asks=(("100.6", "10"),))
    sh = _shadow(make_window(book_pre=thin_pre), mature_passport(depth="20"))
    assert sh.thin is True
    assert sh.label == "THIN"
    assert sh.book_trust == 0.5
    assert _shadow(make_window(book_pre=thin_pre)).thin is False


def test_no_book_after_the_print_is_unknown() -> None:
    sh = _shadow(make_window(book_pre=PRE, path=((T0, PRE.snapshot_copy()),)))
    assert sh.label == "UNKNOWN"
    assert sh.book_trust is None
    assert sh.evidence["books_in_window"] == "0"


def test_tape_trust_duplicates_and_ofi_mismatch() -> None:
    wash = [
        make_trade(T0 + timedelta(milliseconds=500 * (i + 1)), px="100.4", qty="0.7", side="sell")
        for i in range(12)
    ]
    sh = _shadow(make_window(book_pre=PRE, trades=wash))
    assert sh.tape_trust is not None
    assert sh.tape_trust < 0.2
    honest = [
        make_trade(
            T0 + timedelta(milliseconds=500 * (i + 1)),
            px="100.4",
            qty=str(Decimal("0.1") * (i + 1)),
            side="sell",
        )
        for i in range(12)
    ]
    assert _shadow(make_window(book_pre=PRE, trades=honest)).tape_trust == 1.0
    # Asks lifted away (CKS OFI +100) while the mid fell two ticks: book and price disagree.
    pre = make_book(bids=(("100.4", "10"), ("100.3", "10")), asks=(("100.6", "100"),))
    moved = make_book(bids=(("99.9", "10"),), asks=(("100.7", "100"),), seq=2)
    mismatch = make_window(
        book_pre=pre,
        path=((T0 + timedelta(seconds=1), pre.snapshot_copy()), (T0 + timedelta(seconds=2), moved)),
        trades=honest,
    )
    fr = frame(mismatch, Passport("BTCUSDT"))
    assert fr.mid_move_ticks == Decimal("-2")
    assert fr.ofi == Decimal("90")
    assert fr.ofi_rel == Decimal("4.5")
    assert _shadow(mismatch).tape_trust == 0.5


def test_fingerprint_is_deterministic_and_reacts_to_spoof(clean_window) -> None:
    a = _shadow(clean_window)
    b = _shadow(make_window(trades=quiet_prints()))
    assert a.fingerprint == b.fingerprint
    assert len(a.fingerprint) == FINGERPRINT_LEN
    assert a.fingerprint_text.count("-") == FINGERPRINT_LEN - 1
    spoof = _shadow(_vanishing_window({"100.4": "40"}))
    assert spoof.fingerprint[0] == a.fingerprint[0] == 0
    assert spoof.fingerprint[1] == 3
    assert a.fingerprint[1] == 0
