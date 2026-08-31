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
    # F1 max_lev=3 rejects 5x first. That is a reject, not a 4% pass.
    f1 = Sizer(target_risk=Decimal("0.012")).decide(
        lev=Decimal("5"),
        stop_frac=Decimal("0.04"),
        requested_margin=Decimal("0.20"),
    )
    assert f1.action == "reject"
    assert "lev" in f1.reason
    # Even if 5x were allowed, 20%×5×4% = 4% > 1.2% target is reject.
    wide = Sizer(target_risk=Decimal("0.012"), max_lev=Decimal("5")).decide(
        lev=Decimal("5"),
        stop_frac=Decimal("0.04"),
        requested_margin=Decimal("0.20"),
    )
    assert wide.action == "reject"
    assert wide.account_risk == Decimal("0.04")
    assert wide.margin_frac is None
