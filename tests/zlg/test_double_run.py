"""Two runs of the same adds → the same gesture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.memory.registry import Touch
from capitalizator.zlg.gesture import BookAdd, ZLG

T0 = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def test_two_runs_same_label() -> None:
    touch = Touch.create(
        zone_id="z",
        ts=T0,
        trade_px=Decimal("100"),
        trade_qty=Decimal("4"),
    )
    adds = [
        BookAdd(ts=T0 + timedelta(seconds=2), side="bid", px=Decimal("100"), qty=Decimal("2"))
    ]

    def run() -> str:
        return ZLG(tick_size=Decimal("0.1")).classify(
            touch,
            adds,
            Decimal("4"),
            hit_side="bid",
            mid=Decimal("100.25"),
            opp_best=Decimal("100.4"),
        ).gesture

    assert run() == run() == "DEFEND"
