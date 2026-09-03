"""3.14.3 — REFUTED load-bearing claim flattens. UNVERIFIABLE does not."""

from __future__ import annotations

from capitalizator.exec.manage import TradeManager
from capitalizator.risk.schema import FORBIDDEN_ACTIONS


def test_refuted_load_bearing_flattens() -> None:
    got = TradeManager().on_refute(load_bearing=True, verdict="REFUTED")
    assert got is not None
    assert got.action == "flatten"
    assert got.action not in FORBIDDEN_ACTIONS


def test_b_veto_flattens() -> None:
    got = TradeManager().on_refute(load_bearing=True, verdict="veto")
    assert got is not None and got.action == "flatten"


def test_unverifiable_does_not_flatten() -> None:
    assert TradeManager().on_refute(load_bearing=True, verdict="UNVERIFIABLE") is None


def test_non_bearing_refute_does_not_flatten() -> None:
    assert TradeManager().on_refute(load_bearing=False, verdict="REFUTED") is None


def test_pending_does_not_flatten() -> None:
    assert TradeManager().on_refute(load_bearing=True, verdict="pending") is None
