"""2.12.3 — 1 hit is not a guru. 20 misses stay at 0."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.authors.score import weight


def test_one_hit_is_zero() -> None:
    assert weight(1, 1) == Decimal("0")


def test_four_calls_still_zero() -> None:
    assert weight(4, 4) == Decimal("0")


def test_twenty_misses_is_zero() -> None:
    assert weight(0, 20) == Decimal("0")


def test_formula_after_min_n() -> None:
    assert weight(10, 20) == (Decimal("20") / Decimal("40")) * Decimal("0.5")
