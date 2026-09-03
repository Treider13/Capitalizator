"""3.15.5 — three flags True → forbid new longs. Unknown is not a peak."""

from __future__ import annotations

from pathlib import Path

from capitalizator.whales.fragility import forbid_new_long, heatmap_is_entry

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator"


def test_three_true_forbids_new_long() -> None:
    assert (
        forbid_new_long(oi_peak=True, funding_top5=True, thin_book=True) is True
    )


def test_one_false_does_not_forbid() -> None:
    assert (
        forbid_new_long(oi_peak=True, funding_top5=True, thin_book=False) is False
    )


def test_unknown_is_not_invented_peak() -> None:
    assert (
        forbid_new_long(oi_peak=True, funding_top5=True, thin_book=None) is False
    )


def test_heatmap_is_not_an_entry() -> None:
    assert heatmap_is_entry() is False


def test_fragility_flags_gate_the_crowded_side_only() -> None:
    """3.15.5 is wired: the desk computes the flags from its own OI / funding / book
    history and the strategy refuses the crowded side. Unknown inputs never forbid."""
    from capitalizator.whales.fragility import forbid_new_short

    assert forbid_new_long(oi_peak=True, funding_top5=True, thin_book=True) is True
    assert forbid_new_long(oi_peak=True, funding_top5=None, thin_book=True) is False
    assert forbid_new_short(oi_peak=True, funding_bottom5=True, thin_book=True) is True
    assert forbid_new_short(oi_peak=True, funding_bottom5=False, thin_book=True) is False
    text = (SRC / "exec" / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "fragile_long" in text and "fragile_short" in text
