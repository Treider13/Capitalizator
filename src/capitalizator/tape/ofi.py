"""Short Cont–Kukanov–Stoikov OFI in the same interval as the touch.

Cont, Kukanov, Stoikov (2014), The Price Impact of Order Book Events:

  e_n = 1_{P^b_n ≥ P^b_{n-1}} q^b_n − 1_{P^b_n ≤ P^b_{n-1}} q^b_{n-1}
      − 1_{P^a_n ≤ P^a_{n-1}} q^a_n + 1_{P^a_n ≥ P^a_{n-1}} q^a_{n-1}

OFI = sum e_n over consecutive ready books. This is not signed tape / CVD.
`trades` only pins the interval: each must be a print with a known side.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.book.reconstruct import Book
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent

Quote = tuple[Decimal, Decimal, Decimal, Decimal]


class OFI:
    def window(self, trades: Sequence[MarketEvent], book: Sequence[Book]) -> Decimal:
        clf = TapeClassifier()
        for trade in trades:
            clf.taker_side(trade)
        if len(book) < 2:
            raise ValueError("OFI.window needs ≥2 book states")
        quotes = [_quote(b) for b in book]
        total = Decimal("0")
        for i in range(1, len(quotes)):
            total += _e_n(quotes[i - 1], quotes[i])
        return total


def _quote(book: Book) -> Quote:
    if not book.ready:
        raise ValueError("OFI needs a ready book")
    bid, ask = book.best()
    if bid is None or ask is None:
        raise ValueError("OFI needs both best bid and best ask")
    return bid, book.level("bid", str(bid)), ask, book.level("ask", str(ask))


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
