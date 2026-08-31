"""Second entry while open is reject. No average_in field."""

from __future__ import annotations

import pytest

from capitalizator.risk.positions import PositionBook


def test_second_entry_rejected() -> None:
    book = PositionBook()
    assert book.allow_entry() is True
    book.on_open()
    assert book.allow_entry() is False
    with pytest.raises(ValueError, match="already"):
        book.on_open()


def test_flat_allows_again() -> None:
    book = PositionBook()
    book.on_open()
    book.on_flat()
    assert book.allow_entry() is True
