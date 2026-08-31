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


def test_liq_halts() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.mark_liq()
    assert h.allow_entry() is False
    assert h.reason == "liq"
