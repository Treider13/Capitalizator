"""4.18.5 — F1 size stays 1. F4 quarter is explicit and does not raise size."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.nmin import NMIN_SIZE, size_mult


def test_f1_silence_does_not_change_size() -> None:
    assert size_mult(n=3, gesture="SILENCE", phase="f1") == Decimal("1")


def test_f1_n19_does_not_change_size() -> None:
    assert size_mult(n=19, gesture="DEFEND", phase="f1") == Decimal("1")


def test_f4_silence_is_quarter() -> None:
    assert size_mult(n=40, gesture="SILENCE", phase="f4") == Decimal("0.25")


def test_f4_n19_is_quarter() -> None:
    assert size_mult(n=19, gesture="DEFEND", phase="f4") == Decimal("0.25")


def test_never_raises_size() -> None:
    assert size_mult(n=100, gesture="DEFEND", phase="f4") == Decimal("1")
    assert size_mult(n=100, gesture="DEFEND", phase="f1") == Decimal("1")


def test_nmin_size_is_zero_until_decided() -> None:
    assert NMIN_SIZE == Decimal("0")
