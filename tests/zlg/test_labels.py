"""One fixture per ZLG label. SILENCE if max A < γ·q."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

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


def test_mid_equals_print_is_error() -> None:
    with pytest.raises(ValueError, match="mid"):
        _zlg().classify(
            TOUCH,
            [_add("bid", "100", "2")],
            Q,
            hit_side="bid",
            mid=Decimal("100"),
            opp_best=OPP,
        )


def test_add_before_print_ignored() -> None:
    early = BookAdd(ts=T0, side="bid", px=Decimal("100"), qty=Decimal("2"))
    assert _label(early) == "SILENCE"
