"""100k, 3x, stop 2%, target 1% → raw margin 16.67% → reject (cap 10%)."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.sizing import Sizer, Sizing, implied_risk


def test_two_percent_stop_at_3x_needs_more_than_cap() -> None:
    got = Sizer().decide(lev=Decimal("3"), stop_frac=Decimal("0.02"))
    assert got.action == "reject"
    assert "широк" in got.reason


def test_four_percent_stop_at_3x_fits_cap() -> None:
    """0.01 / (3 × 0.04) = 8.33% < 10%."""
    got = Sizer().decide(lev=Decimal("3"), stop_frac=Decimal("0.04"))
    assert got.action == "accept"
    assert got.margin_frac == Decimal("0.01") / (Decimal("3") * Decimal("0.04"))
    assert got.account_risk == Decimal("0.01")


def test_implied_risk_is_product() -> None:
    assert implied_risk(
        margin_frac=Decimal("0.10"),
        lev=Decimal("3"),
        stop_frac=Decimal("0.04"),
    ) == Decimal("0.012")


def test_compute_100k_3x_2pct_rejects() -> None:
    """PHASE-BUILD 1.5.1: raw = 0.01/(3×0.02) = 16.67% > 10% cap."""
    got = Sizing().compute(
        Decimal("100000"),
        Decimal("3"),
        Decimal("0.02"),
        Decimal("0.01"),
    )
    assert got.action == "reject"
    assert "широк" in got.reason


def test_compute_100k_3x_4pct_accepts() -> None:
    got = Sizing().compute(
        Decimal("100000"),
        Decimal("3"),
        Decimal("0.04"),
        Decimal("0.01"),
    )
    assert got.action == "accept"
    assert got.margin_frac == Decimal("0.01") / (Decimal("3") * Decimal("0.04"))
