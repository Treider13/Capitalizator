"""0.4.6 — exchange order list is truth. Local cache follows. No live API.

PHASE-BUILD: a position on the exchange with no local idea → flatten + halt.
This module does not send flatten. It only reports the mismatch.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str


@dataclass(frozen=True)
class PaperPosition:
    symbol: str


@dataclass(frozen=True)
class UnknownPosition:
    flatten: bool
    halt_entries: bool
    alert: str | None


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

    def unknown_position(
        self,
        exchange_positions: Sequence[PaperPosition],
        *,
        local_symbol: str | None,
    ) -> UnknownPosition:
        """Exchange has a position we did not open → CRITICAL, not a new entry."""
        live = {p.symbol for p in exchange_positions if p.symbol}
        if not live:
            return UnknownPosition(False, False, None)
        if local_symbol is None or local_symbol not in live:
            return UnknownPosition(True, True, "CRITICAL")
        extra = live - {local_symbol}
        if extra:
            return UnknownPosition(True, True, "CRITICAL")
        return UnknownPosition(False, False, None)
