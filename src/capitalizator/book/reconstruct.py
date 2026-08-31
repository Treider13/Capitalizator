"""L2 book from snapshot + diffs. Zero size deletes. No ghost levels.

Gap/apply version is Bybit `u` (BookSnapshot.seq). `u=1` after a live book
is a service restart — drop local state (BookDirty), do not patch.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rest_snapshot import BookSnapshot

Side = str


class BookDirty(ValueError):
    """Diff arrived without a snapshot, or after an unhandled gap / restart."""


class Book:
    def __init__(self, *, tick_size: str = "0.1") -> None:
        self.tick_size = Decimal(tick_size)
        self._bids: dict[str, Decimal] = {}
        self._asks: dict[str, Decimal] = {}
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
        return {Decimal(px): sz for px, sz in raw.items()}

    def apply_snapshot(self, snapshot: BookSnapshot) -> None:
        self._bids = {}
        self._asks = {}
        self._put_side(self._bids, snapshot.bids)
        self._put_side(self._asks, snapshot.asks)
        self._seq = snapshot.seq
        self._ready = True

    def apply_diff(
        self,
        bids: tuple[tuple[str, str], ...],
        asks: tuple[tuple[str, str], ...],
        *,
        seq: int,
    ) -> None:
        if not self._ready:
            raise BookDirty("diff before snapshot")
        if self._seq is None:
            raise BookDirty("book has no update id")
        if seq == 1 and self._seq != 1:
            raise BookDirty("bybit u=1 restart; resync required")
        if seq <= self._seq:
            raise SeqFault(f"book u not monotonic: {self._seq} -> {seq}")
        if seq > self._seq + 1:
            raise BookDirty(f"book u gap {self._seq} -> {seq}; resync required")
        self._put_side(self._bids, bids)
        self._put_side(self._asks, asks)
        self._seq = seq

    def _put_side(self, book: dict[str, Decimal], rows: tuple[tuple[str, str], ...]) -> None:
        for px, sz in rows:
            size = Decimal(sz)
            if size == 0:
                book.pop(str(Decimal(px)), None)
                book.pop(px, None)
            else:
                book[str(Decimal(px))] = size

    def best(self) -> tuple[Decimal | None, Decimal | None]:
        bid = max((Decimal(p) for p in self._bids), default=None)
        ask = min((Decimal(p) for p in self._asks), default=None)
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
            if abs(Decimal(price) - center) <= width:
                total += size
        return total

    def imbalance(self, n: int) -> Decimal | None:
        bids = sorted((Decimal(p), s) for p, s in self._bids.items())[-n:]
        asks = sorted((Decimal(p), s) for p, s in self._asks.items())[:n]
        bid_q = sum((s for _, s in bids), Decimal("0"))
        ask_q = sum((s for _, s in asks), Decimal("0"))
        denom = bid_q + ask_q
        if denom == 0:
            return None
        return (bid_q - ask_q) / denom

    def fingerprint(self) -> bytes:
        bids = ",".join(f"{p}:{self._bids[p]}" for p in sorted(self._bids, key=Decimal, reverse=True))
        asks = ",".join(f"{p}:{self._asks[p]}" for p in sorted(self._asks, key=Decimal))
        payload = f"{self._seq}|{bids}|{asks}".encode()
        return sha256(payload).digest()

    def level(self, side: Side, px: str) -> Decimal:
        book = self._bids if side == "bid" else self._asks
        return book.get(str(Decimal(px)), Decimal("0"))
