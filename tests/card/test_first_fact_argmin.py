"""2.11.4 — first_fact = argmin horizon among claims with our frequency.

The field is filled by code. Size does not grow. Unknown horizon dies.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.card.first_fact import RankedClaim, horizon_seconds, pick_by_horizon


def test_fastest_frequent_claim_wins() -> None:
    got = pick_by_horizon(
        [
            RankedClaim(value="author", horizon="1d", n=40),
            RankedClaim(value="DEFEND", horizon="8s", n=20),
            RankedClaim(value="REJECT", horizon="15m", n=25),
        ]
    )
    assert got.tag == "first_fact"
    assert got.first_fact == "DEFEND"
    assert got.size_mult == Decimal("1")


def test_n_under_twenty_is_ignored() -> None:
    got = pick_by_horizon(
        [
            RankedClaim(value="DEFEND", horizon="8s", n=19),
            RankedClaim(value="box", horizon="1h", n=20),
        ]
    )
    assert got.first_fact == "box"
    assert got.size_mult == Decimal("1")


def test_all_below_nmin_is_shadow() -> None:
    got = pick_by_horizon([RankedClaim(value="DEFEND", horizon="8s", n=19)])
    assert got.tag == "shadow_gesture"
    assert got.first_fact is None
    assert got.size_mult == Decimal("1")


def test_silence_is_not_a_fact() -> None:
    got = pick_by_horizon([RankedClaim(value="SILENCE", horizon="8s", n=40)])
    assert got.tag == "shadow_gesture"
    assert got.first_fact is None


def test_unknown_horizon_raises() -> None:
    with pytest.raises(ValueError, match="horizon"):
        pick_by_horizon([RankedClaim(value="DEFEND", horizon="soon", n=20)])


def test_horizon_seconds_order() -> None:
    assert horizon_seconds("8s") < horizon_seconds("15m") < horizon_seconds("1h")
    assert horizon_seconds("1h") < horizon_seconds("1d")
