"""2.10.3 — Y above threshold skips. Unmeasured Y is not a fake thin book."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.risk.prs_cut import decide


def test_thin_y_is_reject() -> None:
    got = decide(Decimal("3"), threshold=Decimal("2"))
    assert got.action == "reject"
    assert got.reason == "prs_thin"


def test_ok_y_is_accept() -> None:
    got = decide(Decimal("1"), threshold=Decimal("2"))
    assert got.action == "accept"
    assert got.reason == "prs_ok"


def test_unmeasured_is_not_thin() -> None:
    got = decide(None, threshold=Decimal("2"))
    assert got.action == "accept"
    assert got.reason == "prs_unmeasured"


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError, match="threshold"):
        decide(Decimal("1"), threshold=Decimal("0"))
