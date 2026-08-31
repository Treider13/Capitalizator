"""Weights rank. They never open size. n<20 stays equal."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.jury.weights import (
    channel_weight,
    equal_before_exam,
    rank_weight,
    weight_opens_size,
)


def test_formula_matches_spec() -> None:
    assert channel_weight(20, Decimal("0.6")) == (
        Decimal("20") / Decimal("40")
    ) * Decimal("0.6")


def test_equal_before_exam() -> None:
    assert equal_before_exam((0, 19, 3)) is True
    assert equal_before_exam((20, 19)) is False
    assert rank_weight(40, Decimal("0.9"), exam_done=False) == Decimal("1")
    assert rank_weight(19, Decimal("0.9"), exam_done=True) == Decimal("1")


def test_after_exam_uses_formula() -> None:
    assert rank_weight(20, Decimal("0.5"), exam_done=True) == channel_weight(
        20, Decimal("0.5")
    )


def test_weight_never_opens_size() -> None:
    w = channel_weight(100, Decimal("1"))
    assert w > 0
    assert weight_opens_size(w) is False
    assert weight_opens_size(Decimal("1")) is False


def test_hit_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="hit"):
        channel_weight(20, Decimal("1.1"))
