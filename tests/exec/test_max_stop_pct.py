"""Э1 — the operator's max_stop_pct is the distance the stop may stretch to.

A cluster / buffer may push the stop farther than the structure, up to that
percent of the entry. Past it the setup is refused (ValueError), never fitted
by pulling the stop back onto the magnet.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.exec.smart_stop import initial_stop

TICK = Decimal("0.1")
ENTRY = Decimal("100000")


def test_stop_may_stretch_up_to_max_stop_pct() -> None:
    # structural 1% below entry; 0.5 ATR buffer sits at 99 000 − 50 = 98 950 (1.05%)
    ok = initial_stop(
        side="buy",
        structural=Decimal("99000"),
        tick=TICK,
        atr=Decimal("100"),
        spread=None,
        entry=ENTRY,
        max_stop_pct=Decimal("0.02"),
    )
    assert ok.stop == Decimal("98950.0")
    assert ok.components["max_stop_pct"] == "0.02"
    assert Decimal(ok.components["stop_pct"]) <= Decimal("0.02")


def test_cluster_push_under_the_ceiling_is_kept() -> None:
    """The band is ticks-wide, so a cluster push is a few ticks; it must stay if
    still under the operator ceiling, and must not be pulled back 'to fit'."""
    pushed = initial_stop(
        side="buy",
        structural=Decimal("99000"),
        tick=TICK,
        atr=Decimal("100"),
        spread=None,
        entry=ENTRY,
        liq_levels=(Decimal("98949.8"),),
        max_stop_pct=Decimal("0.02"),
    )
    assert pushed.moved_for_cluster
    assert Decimal(pushed.components["stop_pct"]) <= Decimal("0.02")
    assert pushed.components["max_stop_pct"] == "0.02"


def test_structural_already_wider_than_max_stop_pct_is_refused() -> None:
    with pytest.raises(ValueError, match="stop_too_wide_pct"):
        initial_stop(
            side="buy",
            structural=Decimal("94000"),  # 6%
            tick=TICK,
            atr=None,
            spread=None,
            entry=ENTRY,
            mode="structural",
            max_stop_pct=Decimal("0.05"),
        )


def test_short_mirrors_the_pct_ceiling() -> None:
    ok = initial_stop(
        side="sell",
        structural=Decimal("101000"),
        tick=TICK,
        atr=Decimal("100"),
        spread=None,
        entry=ENTRY,
        max_stop_pct=Decimal("0.02"),
    )
    assert ok.stop >= Decimal("101000")
    assert Decimal(ok.components["stop_pct"]) <= Decimal("0.02")
    with pytest.raises(ValueError, match="stop_too_wide_pct"):
        initial_stop(
            side="sell",
            structural=Decimal("106000"),
            tick=TICK,
            atr=None,
            spread=None,
            entry=ENTRY,
            mode="structural",
            max_stop_pct=Decimal("0.05"),
        )


def test_max_stop_pct_without_entry_cannot_be_applied() -> None:
    # Never guess the entry. No ceiling is not a silent 5%.
    got = initial_stop(
        side="buy",
        structural=Decimal("94000"),
        tick=TICK,
        atr=None,
        spread=None,
        mode="structural",
        max_stop_pct=Decimal("0.05"),
    )
    assert got.stop == Decimal("94000")
    assert "max_stop_pct" not in got.components
