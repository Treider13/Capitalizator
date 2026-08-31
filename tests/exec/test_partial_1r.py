"""+1R reduces 50%. +2R leaves the rest. Stop path flattens, does not add."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.exec.manage import TradeManager
from capitalizator.risk.schema import FORBIDDEN_ACTIONS


def test_path_to_two_r_takes_half_then_keeps_rest() -> None:
    mgr = TradeManager()
    first = mgr.on_fill(
        side="buy",
        entry=Decimal("100"),
        stop=Decimal("98"),
        fill_px=Decimal("102"),
    )
    assert first is not None
    assert first.action == "reduce"
    assert first.fraction == Decimal("0.5")
    assert mgr.remaining == Decimal("0.5")
    second = mgr.on_fill(
        side="buy",
        entry=Decimal("100"),
        stop=Decimal("98"),
        fill_px=Decimal("104"),
    )
    assert second is None
    assert mgr.remaining == Decimal("0.5")


def test_stop_path_flattens_without_add() -> None:
    mgr = TradeManager()
    got = mgr.on_fill(
        side="buy",
        entry=Decimal("100"),
        stop=Decimal("98"),
        fill_px=Decimal("98"),
    )
    assert got is not None
    assert got.action == "flatten"
    assert mgr.remaining == Decimal("0")
    assert got.action not in FORBIDDEN_ACTIONS


def test_trail_is_last_swing_not_entry() -> None:
    mgr = TradeManager()
    assert mgr.trail_stop(Decimal("101.2")) == Decimal("101.2")
    assert mgr.trail_stop(Decimal("101.2")) != Decimal("100")
