"""No move_to_be_at_pct=0.02. +2% price with a wide stop is not a flatten."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from capitalizator.exec.manage import TradeManager

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec" / "manage.py"


def test_source_has_no_mechanical_be_knob() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "move_to_be_at_pct" not in text
    assert "0.02" not in text
    assert not hasattr(TradeManager, "move_to_be_at_pct")


def test_two_percent_price_is_not_be() -> None:
    """Stop 4% away. +2% is 0.5R — no reduce, no flatten to entry."""
    mgr = TradeManager()
    got = mgr.on_fill(
        side="buy",
        entry=Decimal("100"),
        stop=Decimal("96"),
        fill_px=Decimal("102"),
    )
    assert got is None
    assert mgr.remaining == Decimal("1")
    assert mgr.reduced_at_1r is False
