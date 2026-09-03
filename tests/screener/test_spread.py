"""Spread 0.4% vs typical move 0.3% → reject. Maker fees are in the cost."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.screener.filters import Screener


def test_spread_wider_than_target_is_rejected() -> None:
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.004"),
            typical_move=Decimal("0.003"),
        )
        is False
    )


def test_tight_spread_is_ok() -> None:
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
        )
        is True
    )


def test_unlock_today_rejects() -> None:
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            unlock_today=True,
        )
        is False
    )


def test_unlock_tomorrow_rejects() -> None:
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            unlock_tomorrow=True,
        )
        is False
    )


def test_symbol_outside_week0_rejects() -> None:
    assert (
        Screener().ok(
            "SOLUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
        )
        is False
    )


def test_delisted_and_funding_extreme_reject() -> None:
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            delisted=True,
        )
        is False
    )
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            funding_extreme=True,
        )
        is False
    )
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            volume_ok=False,
        )
        is False
    )


def test_unmeasured_typical_move_skips_the_screen_but_zero_still_rejects() -> None:
    # None = no ATR yet: the volatility screen is not measured (the EV gate decides);
    # a measured zero move is a flat market and is refused.
    assert Screener().ok("BTCUSDT", spread_frac=Decimal("0.001"), typical_move=None) is True
    assert Screener().ok("BTCUSDT", spread_frac=Decimal("0.001"), typical_move=Decimal("0")) is False
    assert Screener().ok("BTCUSDT", spread_frac=Decimal("-0.001"), typical_move=None) is False
