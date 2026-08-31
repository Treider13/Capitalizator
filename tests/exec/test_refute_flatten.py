"""3.14.3 — REFUTED load-bearing claim flattens. UNVERIFIABLE does not."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.exec.manage import TradeManager
from capitalizator.risk.schema import FORBIDDEN_ACTIONS


def test_refuted_load_bearing_flattens() -> None:
    mgr = TradeManager()
    mgr.remaining = Decimal("1")
    got = mgr.on_refute(load_bearing=True, verdict="REFUTED")
    assert got is not None
    assert got.action == "flatten"
    assert mgr.remaining == Decimal("0")
    assert got.action not in FORBIDDEN_ACTIONS


def test_unverifiable_does_not_flatten() -> None:
    mgr = TradeManager()
    assert mgr.on_refute(load_bearing=True, verdict="UNVERIFIABLE") is None
    assert mgr.remaining == Decimal("1")


def test_non_bearing_refute_does_not_flatten() -> None:
    mgr = TradeManager()
    assert mgr.on_refute(load_bearing=False, verdict="REFUTED") is None
    assert mgr.remaining == Decimal("1")


def test_pending_does_not_flatten() -> None:
    mgr = TradeManager()
    assert mgr.on_refute(load_bearing=True, verdict="pending") is None
