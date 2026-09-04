"""AMD liquidity phase from measured window facts. Missing facts → unknown. No size."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.tape.phase import classify


def test_missing_fact_is_unknown() -> None:
    assert classify(ofi=None, cvd=Decimal("1"), mid_ticks=Decimal("0"), eaten=False) == "unknown"
    assert classify(ofi=Decimal("1"), cvd=None, mid_ticks=Decimal("0"), eaten=False) == "unknown"
    assert classify(ofi=Decimal("1"), cvd=Decimal("1"), mid_ticks=None, eaten=False) == "unknown"


def test_eaten_and_price_reclaimed_is_manipulate() -> None:
    assert (
        classify(
            ofi=Decimal("3"),
            cvd=Decimal("-2"),
            mid_ticks=Decimal("0"),
            eaten=True,
        )
        == "manipulate"
    )


def test_flow_and_price_agree_is_distribute() -> None:
    assert (
        classify(
            ofi=Decimal("2"),
            cvd=Decimal("4"),
            mid_ticks=Decimal("3"),
            eaten=False,
        )
        == "distribute"
    )


def test_book_absorbs_tape_is_accumulate() -> None:
    assert (
        classify(
            ofi=Decimal("3"),
            cvd=Decimal("-2"),
            mid_ticks=Decimal("0"),
            eaten=False,
        )
        == "accumulate"
    )


def test_noise_is_unknown() -> None:
    assert (
        classify(
            ofi=Decimal("0"),
            cvd=Decimal("0"),
            mid_ticks=Decimal("0"),
            eaten=False,
        )
        == "unknown"
    )
