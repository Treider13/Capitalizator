"""Two shadow widths, no orders, champion stays. promote() raises."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.champion.shadow_width import ShadowWidth


def test_two_challengers_and_no_promote() -> None:
    book = ShadowWidth()
    rows = book.report()
    assert [row["width"] for row in rows] == [Decimal("0.8"), Decimal("1.2")]
    assert all(row["orders"] is False for row in rows)
    assert book.champion_width == Decimal("1")
    with pytest.raises(ValueError, match="no auto promote"):
        book.promote()
    assert book.champion_width == Decimal("1")
