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
