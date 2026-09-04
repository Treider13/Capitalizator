"""One 8s window → OFI L1, multi-level OFI, CVD, AMD phase, book check.

Facts only. Invalid book → no invented OFI. CVD still reads the tape.
Does not open size.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from capitalizator.book.reconstruct import Book
from capitalizator.book.validate import validate
from capitalizator.tape.cvd import CVD
from capitalizator.tape.ofi import OFI, OFI_LEVELS
from capitalizator.tape.phase import classify
from capitalizator.types import MarketEvent


def snapshot(
    *,
    prints: Sequence[MarketEvent],
    books: Sequence[Book],
    eaten: bool | None,
    tick: Decimal,
    probe: Book | None = None,
) -> dict[str, Any]:
    last = books[-1] if books else probe
    check = validate(last)
    ofi: Decimal | None = None
    ofi_levels: Decimal | None = None
    if check.ok and len(books) >= 2:
        try:
            ofi = OFI().window(prints, books, levels=1)
        except ValueError:
            ofi = None
        try:
            ofi_levels = OFI().window(prints, books, levels=OFI_LEVELS)
        except ValueError:
            ofi_levels = None
    cvd: Decimal | None
    try:
        cvd = CVD().window(prints)
    except ValueError:
        cvd = None
    mid = _mid_ticks(books[0], books[-1], tick) if check.ok and len(books) >= 2 else None
    return {
        "ofi": None if ofi is None else str(ofi),
        "ofi_levels": None if ofi_levels is None else str(ofi_levels),
        "cvd": None if cvd is None else str(cvd),
        "phase": classify(ofi=ofi, cvd=cvd, mid_ticks=mid, eaten=eaten),
        "book_ok": check.ok,
        "book_reason": check.reason,
    }


def _mid_ticks(pre: Book, end: Book, tick: Decimal) -> Decimal | None:
    if tick <= 0:
        return None
    b0, a0 = pre.best()
    b1, a1 = end.best()
    if b0 is None or a0 is None or b1 is None or a1 is None:
        return None
    return ((b1 + a1) / 2 - (b0 + a0) / 2) / tick
