"""0.4.6 — exchange order list is truth. Local cache follows. No live API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str


def yaml_reconcile_s() -> int:
    from capitalizator.risk.session import load_time_config

    seconds = int(load_time_config()["reconcile_s"])
    if seconds <= 0:
        raise ValueError("reconcile_s must be > 0")
    return seconds


class Reconciler:
    def __init__(self, *, reconcile_s: int | None = None) -> None:
        self.reconcile_s = yaml_reconcile_s() if reconcile_s is None else reconcile_s
        if self.reconcile_s <= 0:
            raise ValueError("reconcile_s must be > 0")
        self.local: dict[str, PaperOrder] = {}

    def tick(self, exchange_orders: Mapping[str, PaperOrder]) -> None:
        self.local = dict(exchange_orders)
