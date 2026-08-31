"""0.4.6 — exchange order list is truth. Local cache follows. No live API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str


class Reconciler:
    def __init__(self) -> None:
        self.local: dict[str, PaperOrder] = {}

    def tick(self, exchange_orders: Mapping[str, PaperOrder]) -> None:
        self.local = dict(exchange_orders)
