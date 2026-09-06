"""Constant-memory trade block accumulator; no per-print list rescans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Flow:
    n: int = 0
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: float = 0
    delta: float = 0
    largest: float = 0
    block_volume: float = 0

    def __len__(self) -> int:
        return self.n

    def append(self, trade: tuple[float, float, int]) -> None:
        price, qty, side = trade
        if not self.n:
            self.open = self.high = self.low = price
        self.high, self.low = max(self.high, price), min(self.low, price)
        self.close = price
        self.volume += qty
        self.delta += qty * side
        self.largest = max(self.largest, qty)
        self.n += 1

    def clear(self) -> None:
        self.n = 0
        self.open = self.high = self.low = self.close = 0
        self.volume = self.delta = self.largest = self.block_volume = 0
