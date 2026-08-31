"""TCA table exists. Empty median is None — not a fake perfect fill."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.exec.tca_demo import TcaRow, TcaTable


def test_empty_median_is_none() -> None:
    assert TcaTable().median_slip_ticks() is None


def test_median_of_known_slips() -> None:
    table = TcaTable()
    table.add(
        TcaRow(
            model_px=Decimal("100"),
            fill_px=Decimal("100.1"),
            delay_s=Decimal("0"),
            tick=Decimal("0.1"),
        )
    )
    table.add(
        TcaRow(
            model_px=Decimal("100"),
            fill_px=Decimal("100.3"),
            delay_s=Decimal("1"),
            tick=Decimal("0.1"),
        )
    )
    assert table.median_slip_ticks() == Decimal("2")
