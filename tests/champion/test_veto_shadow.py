"""2.9.5 — veto-off is a challenger report. promote() raises."""

from __future__ import annotations

import pytest

from capitalizator.champion.veto_shadow import VetoShadow


def test_two_rows_no_orders_no_promote() -> None:
    book = VetoShadow()
    rows = book.report()
    assert [row["veto"] for row in rows] == [True, False]
    assert all(row["orders"] is False for row in rows)
    with pytest.raises(ValueError, match="no auto promote"):
        book.promote()
