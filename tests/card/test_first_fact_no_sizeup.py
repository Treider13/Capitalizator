"""n<20 or SILENCE → shadow_gesture. Size never grows."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.card.first_fact import resolve


def test_n_under_twenty_does_not_size_up() -> None:
    got = resolve("DEFEND", 19)
    assert got.tag == "shadow_gesture"
    assert got.first_fact is None
    assert got.size_mult == Decimal("1")


def test_silence_does_not_size_up() -> None:
    got = resolve("SILENCE", 40)
    assert got.tag == "shadow_gesture"
    assert got.size_mult == Decimal("1")


def test_n_twenty_still_does_not_raise_lots() -> None:
    """Frequency tags the fact. It does not map DEFEND to more lots."""
    got = resolve("DEFEND", 20)
    assert got.first_fact == "DEFEND"
    assert got.size_mult == Decimal("1")
