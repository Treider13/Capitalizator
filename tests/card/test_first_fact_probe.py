"""Probe: a printed book gesture with n<n_min is a small ticket, not silence.

SILENCE / missing gesture stay shadow. Size never grows past 1.
"""

from __future__ import annotations

from decimal import Decimal

from capitalizator.card.first_fact import PROBE_SIZE, resolve


def test_defend_under_nmin_is_probe_not_shadow() -> None:
    got = resolve("DEFEND", 8)
    assert got.tag == "probe_gesture"
    assert got.first_fact == "DEFEND"
    assert got.size_mult == PROBE_SIZE
    assert got.size_mult == Decimal("0.40")
    assert got.size_mult < Decimal("1")


def test_improve_under_nmin_is_probe() -> None:
    got = resolve("IMPROVE", 19)
    assert got.tag == "probe_gesture"
    assert got.first_fact == "IMPROVE"
    assert got.size_mult == Decimal("0.40")


def test_silence_stays_shadow_and_does_not_open_size() -> None:
    got = resolve("SILENCE", 40)
    assert got.tag == "shadow_gesture"
    assert got.first_fact is None
    assert got.size_mult == Decimal("1")


def test_missing_gesture_stays_shadow() -> None:
    got = resolve(None, 8)
    assert got.tag == "shadow_gesture"
    assert got.first_fact is None
    assert got.size_mult == Decimal("1")


def test_mature_defend_is_full_fact_not_probe() -> None:
    got = resolve("DEFEND", 20)
    assert got.tag == "first_fact"
    assert got.first_fact == "DEFEND"
    assert got.size_mult == Decimal("1")


def test_probe_never_raises_size_above_one() -> None:
    for n in (0, 1, 8, 19, 20, 100):
        assert resolve("DEFEND", n).size_mult <= Decimal("1")
