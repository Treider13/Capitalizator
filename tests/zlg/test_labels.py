"""One fixture per ZLG label. SILENCE if max A < γ·q."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.memory.registry import Touch
from capitalizator.zlg.gesture import ZLG, BookAdd, BookSide

TICK = Decimal("0.1")
T0 = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
TOUCH = Touch.create(
    zone_id="z",
    ts=T0,
    trade_px=Decimal("100"),
    trade_qty=Decimal("4"),
)
MID = Decimal("100.25")
OPP = Decimal("100.4")
Q = Decimal("4")


def _zlg() -> ZLG:
    return ZLG(tick_size=TICK)


def _add(side: BookSide, px: str, qty: str, *, seconds: float = 1) -> BookAdd:
    return BookAdd(
        ts=T0 + timedelta(seconds=seconds),
        side=side,
        px=Decimal(px),
        qty=Decimal(qty),
    )


def _label(*adds: BookAdd) -> str:
    return _zlg().classify(
        TOUCH,
        adds,
        Q,
        hit_side="bid",
        mid=MID,
        opp_best=OPP,
    ).gesture


def test_defend() -> None:
    assert _label(_add("bid", "100", "2")) == "DEFEND"


def test_retreat() -> None:
    assert _label(_add("bid", "99.7", "2")) == "RETREAT"


def test_improve() -> None:
    assert _label(_add("bid", "100.2", "2")) == "IMPROVE"


def test_fade() -> None:
    assert _label(_add("ask", "100.4", "2")) == "FADE"


def test_silence_when_add_below_gamma_q() -> None:
    """γ=0.25, q=4 → threshold 1. Add 0.5 → SILENCE."""
    assert _label(_add("bid", "100", "0.5")) == "SILENCE"


def test_mid_equals_print_is_silence() -> None:
    got = _zlg().classify(
        TOUCH,
        [_add("bid", "100", "2")],
        Q,
        hit_side="bid",
        mid=Decimal("100"),
        opp_best=OPP,
    )
    assert got.gesture == "SILENCE"
    assert got.a_same == Decimal("0")


def test_add_before_print_ignored() -> None:
    early = BookAdd(ts=T0, side="bid", px=Decimal("100"), qty=Decimal("2"))
    assert _label(early) == "SILENCE"


def test_survived_liquidity_ignores_flashed_quotes_and_keeps_executed_ones() -> None:
    """Jury §3.2: a quote added and pulled inside the window is not a DEFEND; a quote
    that traded (prints at its price) is not a pull; young survivors are pro-rated."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from capitalizator.zlg.gesture import BookAdd, BookPull, survived_adds

    t0 = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=8)
    px = Decimal("100")
    flash = BookAdd(ts=t0 + timedelta(seconds=1), side="bid", px=px, qty=Decimal("25"))
    real = BookAdd(ts=t0 + timedelta(seconds=1, milliseconds=500), side="bid", px=Decimal("99.9"), qty=Decimal("10"))
    late = BookAdd(ts=t0 + timedelta(seconds=7), side="bid", px=Decimal("99.8"), qty=Decimal("10"))
    pull_flash = BookPull(ts=t0 + timedelta(seconds=3), side="bid", px=px, qty=Decimal("25"))
    # `real` shrinks by 4 right after a print at 99.9 → executed, not pulled
    eaten = BookPull(ts=t0 + timedelta(seconds=5), side="bid", px=Decimal("99.9"), qty=Decimal("4"))
    prints = [(t0 + timedelta(seconds=4, milliseconds=900), Decimal("99.9"))]
    out = dict(survived_adds([flash, real, late], [pull_flash, eaten], prints, t0=t0, t1=t1))
    assert flash not in out  # shown and pulled → nothing survived
    assert out[real] == Decimal("10")  # executed against, still counts in full (alive 6.5s ≥ 2s)
    assert out[late] == Decimal("10") * Decimal("0.5")  # alive 1s of the 2s needed → half credit
    # without prints the same shrink IS a pull
    out2 = dict(survived_adds([real], [eaten], [], t0=t0, t1=t1))
    assert out2[real] == Decimal("6")
