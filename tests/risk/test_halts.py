"""Day −3.1% blocks a new entry. Flatten is not this module."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.halts import Halts


def test_day_minus_three_point_one_rejects() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.update(Decimal("96900"))
    assert h.allow_entry() is False
    assert h.reason == "day"


def test_flat_day_allows() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.update(Decimal("99900"))
    assert h.allow_entry() is True


def test_week_minus_six_rejects() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.update(Decimal("98000"))
    h.new_day(Decimal("98000"))
    h.update(Decimal("96000"))
    h.new_day(Decimal("96000"))
    h.update(Decimal("93900"))
    assert h.allow_entry() is False
    assert h.reason == "week"


def test_peak_minus_twenty_five_rejects() -> None:
    h = Halts(start_equity=Decimal("76000"), peak=Decimal("100000"))
    h.update(Decimal("74999"))
    assert h.allow_entry() is False
    assert h.reason == "peak"


def test_liq_halts() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.mark_liq()
    assert h.allow_entry() is False
    assert h.reason == "liq"


def test_exact_minus_three_halts() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.update(Decimal("97000"))
    assert h.allow_entry() is False
    assert h.reason == "day"


def test_exact_minus_six_week_halts() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.update(Decimal("98000"))
    h.new_day(Decimal("98000"))
    h.update(Decimal("96000"))
    h.new_day(Decimal("96000"))
    h.update(Decimal("94000"))
    assert h.allow_entry() is False
    assert h.reason == "week"


def test_exact_minus_twenty_five_peak_halts() -> None:
    h = Halts(start_equity=Decimal("76000"), peak=Decimal("100000"))
    h.update(Decimal("75000"))
    assert h.allow_entry() is False
    assert h.reason == "peak"


def test_liq_reason_does_not_rewrite() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.mark_liq()
    h.update(Decimal("96900"))
    assert h.reason == "liq"
    got = h.state(
        day_pnl_pct=Decimal("-0.031"),
        week_pnl_pct=Decimal("0"),
        dd_from_peak=Decimal("0"),
        liq_flag=False,
    )
    assert got.reason == "liq"


def test_state_day_minus_three_point_one() -> None:
    h = Halts(start_equity=Decimal("100000"))
    got = h.state(
        day_pnl_pct=Decimal("-0.031"),
        week_pnl_pct=Decimal("0"),
        dd_from_peak=Decimal("0"),
        liq_flag=False,
    )
    assert got.halted is True
    assert got.reason == "day"
    assert h.allow_entry() is False
