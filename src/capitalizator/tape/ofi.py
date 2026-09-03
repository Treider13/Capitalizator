"""Short Cont–Kukanov–Stoikov OFI in the same interval as the touch.

Cont, Kukanov, Stoikov (2014), The Price Impact of Order Book Events:

  e_n = 1_{P^b_n ≥ P^b_{n-1}} q^b_n − 1_{P^b_n ≤ P^b_{n-1}} q^b_{n-1}
      − 1_{P^a_n ≤ P^a_{n-1}} q^a_n + 1_{P^a_n ≥ P^a_{n-1}} q^a_{n-1}

OFI = sum e_n over consecutive ready books. `levels=1` is best bid/ask (the
original CKS number). `levels>1` adds the same e_n at each deeper pair that
both books actually have. A missing deeper level is skipped, not invented.

This is not signed tape / CVD. `trades` only pins the interval: each must be
a print with a known side.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.book.reconstruct import Book
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent

Quote = tuple[Decimal, Decimal, Decimal, Decimal]
OFI_LEVELS = 5


class OFI:
    def window(
        self, trades: Sequence[MarketEvent], book: Sequence[Book], *, levels: int = 1
    ) -> Decimal:
        if levels < 1:
            raise ValueError("OFI levels must be >= 1")
        clf = TapeClassifier()
        for trade in trades:
            clf.taker_side(trade)
        if len(book) < 2:
            raise ValueError("OFI.window needs ≥2 book states")
        total = Decimal("0")
        for i in range(1, len(book)):
            total += _pair(book[i - 1], book[i], levels)
        return total


def _pair(prev: Book, curr: Book, levels: int) -> Decimal:
    total = _e_n(_quote(prev), _quote(curr))
    for depth in range(1, levels):
        q0 = _quote_at(prev, depth)
        q1 = _quote_at(curr, depth)
        if q0 is None or q1 is None:
            continue
        total += _e_n(q0, q1)
    return total


def _quote(book: Book) -> Quote:
    if not book.ready:
        raise ValueError("OFI needs a ready book")
    bid, ask = book.best()
    if bid is None or ask is None:
        raise ValueError("OFI needs both best bid and best ask")
    return bid, book.level("bid", str(bid)), ask, book.level("ask", str(ask))


def _quote_at(book: Book, depth: int) -> Quote | None:
    if not book.ready:
        raise ValueError("OFI needs a ready book")
    bids = sorted(book.levels("bid").items(), reverse=True)
    asks = sorted(book.levels("ask").items())
    if depth >= len(bids) or depth >= len(asks):
        return None
    pb, qb = bids[depth]
    pa, qa = asks[depth]
    return pb, qb, pa, qa


def _e_n(prev: Quote, curr: Quote) -> Decimal:
    pb0, qb0, pa0, qa0 = prev
    pb1, qb1, pa1, qa1 = curr
    e = Decimal("0")
    if pb1 >= pb0:
        e += qb1
    if pb1 <= pb0:
        e -= qb0
    if pa1 <= pa0:
        e -= qa1
    if pa1 >= pa0:
        e += qa0
    return e
