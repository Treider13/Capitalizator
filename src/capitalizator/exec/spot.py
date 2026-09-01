"""P5 — variant-2 spot rail. Listing is a proposal. Order only after human ack.

Does not import signer. Does not send. Telegram is not a source.
Ticker outside the 24 perps stays spot_proposal until ack.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from capitalizator.card.live import CardLive
from capitalizator.ops.knowledge import Knowledge
from capitalizator.screener.universe import Universe, load_desk_universe
from capitalizator.types import require_utc

CLAIM_PREFIX = "spot_ack:"


def perp_symbols(universe: Universe | None = None) -> frozenset[str]:
    book = universe if universe is not None else load_desk_universe()
    return frozenset(book.symbols)


def in_perp_universe(symbol: str, universe: Universe | None = None) -> bool:
    return symbol in perp_symbols(universe)


class SpotAdapter:
    """Human ack opens the rail. Without ack the adapter never yields an intent."""

    def __init__(self, knowledge: Knowledge | None = None) -> None:
        self.knowledge = knowledge

    def ack(self, symbol: str, *, ack: bool, ts: datetime) -> dict[str, Any]:
        if self.knowledge is None:
            raise FileNotFoundError("no knowledge db")
        if not ack:
            raise ValueError("ack required")
        if not symbol or not symbol.endswith("USDT"):
            raise ValueError("spot ack needs a USDT symbol")
        when = require_utc(ts)
        payload = {"acked": True, "ts": when.isoformat(), "symbol": symbol}
        self.knowledge.put_spot_ack(symbol, payload)
        return payload

    def acked(self, symbol: str) -> bool:
        if self.knowledge is None:
            return False
        raw = self.knowledge.get_spot_ack(symbol)
        return bool(raw and raw.get("acked") is True)

    def allow(self, card: CardLive, *, acked: bool | None = None) -> bool:
        """Perp cards pass. spot_proposal needs a stored or passed ack."""
        if card.venue != "spot_proposal":
            return True
        ok = self.acked(card.symbol) if acked is None else acked
        return bool(ok)

    def propose(self, card: CardLive, *, acked: bool | None = None) -> None:
        """Never returns an order. Rail-closed → None. Rail-open still None (no send)."""
        if not self.allow(card, acked=acked):
            return None
        return None
