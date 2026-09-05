"""Score drop flattens the remainder. It never adds size."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.hyexec.score_exit import remainder_action


def test_score_drop_flattens() -> None:
    assert (
        remainder_action(
            score_now=Decimal("0.40"),
            score_entry=Decimal("0.70"),
            drop=Decimal("0.20"),
        )
        == "flatten"
    )


def test_score_hold_when_still_above_drop() -> None:
    assert (
        remainder_action(
            score_now=Decimal("0.65"),
            score_entry=Decimal("0.70"),
            drop=Decimal("0.20"),
        )
        == "hold"
    )


def test_score_exit_cannot_add() -> None:
    act = remainder_action(
        score_now=Decimal("0.99"),
        score_entry=Decimal("0.70"),
        drop=Decimal("0.20"),
    )
    assert act != "add"
    assert act != "add_in_profit"


def test_expand_with_live_structure_holds_on_score_drop() -> None:
    assert (
        remainder_action(
            score_now=Decimal("0.40"),
            score_entry=Decimal("0.70"),
            drop=Decimal("0.20"),
            expand=True,
            structure_ok=True,
        )
        == "hold"
    )


def test_expand_dead_structure_still_flattens() -> None:
    assert (
        remainder_action(
            score_now=Decimal("0.40"),
            score_entry=Decimal("0.70"),
            drop=Decimal("0.20"),
            expand=True,
            structure_ok=False,
        )
        == "flatten"
    )
