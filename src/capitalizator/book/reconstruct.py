"""L2 book from snapshot + diffs. Zero size deletes. No ghost levels.

Law is Bybit `orderbook.{depth}` (recorder topic `orderbook.200`), not Full-OB:

  https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook

  * After subscribe: a `snapshot`, then `delta`. A later `snapshot` resets.
  * Delta: size 0 deletes the price; else insert/update.
  * `u=1` is snapshot data after a service restart — overwrite the local book
    with that message. This page does not say fetch REST (that is Full-OB).
  * Same `u` may repeat on L1 idle. The page does not say wipe on a skipped `u`.

CCXT `pro/bybit.ts` `handleOrderBook`: `type===snapshot` → `reset`, else
`handleDeltas`. No `u` wipe. Nautilus `websocket/parse.rs`: snapshot → CLEAR+ADD,
else UPDATE. Hummingbot Bybit perp: WS `orderbook.200`; REST `/v5/market/orderbook`
for its snapshot message; local nonce, not Bybit `u`.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from capitalizator.recorder.rest_snapshot import BookSnapshot

Side = str


class BookDirty(ValueError):
    """Delta arrived before any snapshot. Not a reason to invent levels."""


def _canon(value: Decimal) -> str:
    """Same number, same text: 60000.0 and 60000 fingerprint equal."""
    return format(value.normalize(), "f")


class Book:
    def __init__(self, *, tick_size: str = "0.1") -> None:
        self.tick_size = Decimal(tick_size)
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._seq: int | None = None
        self._ready = False

    @property
    def seq(self) -> int | None:
        return self._seq

    @property
    def ready(self) -> bool:
        return self._ready

    def levels(self, side: Side) -> dict[Decimal, Decimal]:
        raw = self._bids if side == "bid" else self._asks
        return dict(raw)

    def apply_snapshot(self, snapshot: BookSnapshot) -> None:
        self._replace(snapshot.bids, snapshot.asks, seq=snapshot.seq)

    def apply_diff(
        self,
        bids: tuple[tuple[str, str], ...],
        asks: tuple[tuple[str, str], ...],
        *,
        seq: int,
    ) -> None:
        if seq == 1:
            # Official: u=1 is snapshot data after a service restart. Overwrite.
            self._replace(bids, asks, seq=1)
            return
        if not self._ready or self._seq is None:
            raise BookDirty("diff before snapshot")
        if seq <= self._seq:
            return
        # Official orderbook.200 and CCXT apply the delta. They do not empty
        # the book because `u` skipped a number (that wipe blanked SOLUSDT).
        self._put_side(self._bids, bids)
        self._put_side(self._asks, asks)
        self._seq = seq

    def _replace(
        self,
        bids: tuple[tuple[str, str], ...],
        asks: tuple[tuple[str, str], ...],
        *,
        seq: int,
    ) -> None:
        self._bids = {}
        self._asks = {}
        self._put_side(self._bids, bids)
        self._put_side(self._asks, asks)
        self._seq = seq
        self._ready = True

    def _put_side(self, book: dict[Decimal, Decimal], rows: tuple[tuple[str, str], ...]) -> None:
        for px, sz in rows:
            price = Decimal(px)
            size = Decimal(sz)
            if size < 0:
                raise ValueError(f"level size must be >= 0, got {size}")
            if size == 0:
                book.pop(price, None)
            else:
                book[price] = size

    def best(self) -> tuple[Decimal | None, Decimal | None]:
        bid = max(self._bids, default=None)
        ask = min(self._asks, default=None)
        return bid, ask

    def spread(self) -> Decimal | None:
        bid, ask = self.best()
        if bid is None or ask is None:
            return None
        return ask - bid

    def depth_near(self, side: Side, px: str, ticks: int) -> Decimal:
        center = Decimal(px)
        width = self.tick_size * ticks
        book = self._bids if side == "bid" else self._asks
        total = Decimal("0")
        for price, size in book.items():
            if abs(price - center) <= width:
                total += size
        return total

    def imbalance(self, n: int) -> Decimal | None:
        if n < 1:
            raise ValueError("imbalance n must be >= 1")
        bids = sorted(self._bids.items())[-n:]
        asks = sorted(self._asks.items())[:n]
        bid_q = sum((s for _, s in bids), Decimal("0"))
        ask_q = sum((s for _, s in asks), Decimal("0"))
        denom = bid_q + ask_q
        if denom == 0:
            return None
        return (bid_q - ask_q) / denom

    def fingerprint(self) -> bytes:
        bid_keys = sorted(self._bids, reverse=True)
        ask_keys = sorted(self._asks)
        bids = ",".join(f"{_canon(p)}:{_canon(self._bids[p])}" for p in bid_keys)
        asks = ",".join(f"{_canon(p)}:{_canon(self._asks[p])}" for p in ask_keys)
        payload = f"{self._seq}|{bids}|{asks}".encode()
        return sha256(payload).digest()

    def level(self, side: Side, px: str) -> Decimal:
        book = self._bids if side == "bid" else self._asks
        return book.get(Decimal(px), Decimal("0"))

    def snapshot_copy(self) -> Book:
        """Deep copy of levels at this instant. Used as book_pre on a touch."""
        clone = Book(tick_size=str(self.tick_size))
        clone._bids = dict(self._bids)
        clone._asks = dict(self._asks)
        clone._seq = self._seq
        clone._ready = self._ready
        return clone

    def with_level(self, side: Side, px: Decimal, size: Decimal) -> Book:
        """Copy with one level set (0 removes). Same seq. This book is not changed.

        For ОКО's Mirror, which injects synthetic walls into a replayed path.
        Not a diff: no sequence check, no gap law. Never used on the live book.
        """
        if not self._ready:
            raise BookDirty("with_level needs a ready book")
        if side not in {"bid", "ask"}:
            raise ValueError("side must be bid|ask")
        clone = self.snapshot_copy()
        clone._put_side(clone._bids if side == "bid" else clone._asks, ((str(px), str(size)),))
        return clone
