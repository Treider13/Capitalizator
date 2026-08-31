"""20% margin × 5x × 4% stop = 4% account risk → reject. Not a pass."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.sizing import Sizer, implied_risk


def test_wide_alt_at_five_x_is_rejected() -> None:
    risk = implied_risk(
        margin_frac=Decimal("0.20"),
        lev=Decimal("5"),
        stop_frac=Decimal("0.04"),
    )
    assert risk == Decimal("0.04")
    got = Sizer(target_risk=Decimal("0.012")).decide(
        lev=Decimal("5"),
        stop_frac=Decimal("0.04"),
        requested_margin=Decimal("0.20"),
    )
    assert got.action == "reject"
    assert got.margin_frac is None
