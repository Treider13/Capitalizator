"""Is this book a market we may read? Does not invent levels. Does not open size.

ready ∧ both sides ∧ bid < ask. A crossed or locked book is not a quote.
"""

from __future__ import annotations

from dataclasses import dataclass

from capitalizator.book.reconstruct import Book


@dataclass(frozen=True)
class BookCheck:
    ok: bool
    reason: str | None


def validate(book: Book | None) -> BookCheck:
    if book is None or not book.ready:
        return BookCheck(False, "not_ready")
    bid, ask = book.best()
    if bid is None or ask is None:
        return BookCheck(False, "empty_side")
    if bid > ask:
        return BookCheck(False, "crossed")
    if bid == ask:
        return BookCheck(False, "locked")
    return BookCheck(True, None)
