"""Separate spot L2 state and explicit, receipt-time cross-market entry checks.

Displayed liquidity is evidence, not identification of a participant or intent.
Neither spot sizes nor prices are used to simulate futures execution capacity.
"""

from __future__ import annotations

import math
from typing import Any

from capitalizator.fusion.config import Config


def book_metrics(bids: dict[float, float], asks: dict[float, float]) -> dict[str, Any]:
    if not bids or not asks or max(bids) >= min(asks):
        return {"valid": False}
    bid, ask = max(bids), min(asks)
    bid_levels = sorted(bids.items(), reverse=True)[:50]
    ask_levels = sorted(asks.items())[:50]
    buy = sum(p * q for p, q in bid_levels)
    sell = sum(p * q for p, q in ask_levels)
    bid_qty, ask_qty = sum(q for _, q in bid_levels), sum(q for _, q in ask_levels)
    if (
        not math.isfinite(buy + sell)
        or buy + sell <= 0
        or not math.isfinite(bid_qty + ask_qty)
        or bid_qty + ask_qty <= 0
    ):
        return {"valid": False}
    mid = bid + (ask - bid) / 2
    return {
        "valid": True,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "bid_notional": buy,
        "ask_notional": sell,
        "imbalance": (bid_qty - ask_qty) / (bid_qty + ask_qty),
        "spread_bps": (ask - bid) / mid * 10000,
    }


class SpotBook:
    """Mutated only by the existing symbol actor; generations reject old sockets."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.generation = -1
        self.status = "discovery_pending"
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.u = 0
        self.at = 0.0
        self.exchange_at = 0.0
        self.received_mono: float | None = None

    def ingest(self, kind: str, frame: dict[str, Any], at: float) -> None:
        try:
            self._ingest(kind, frame, at)
        except (ValueError, KeyError, ArithmeticError, TypeError):
            self.bids.clear()
            self.asks.clear()
            self.u = 0
            self.status = "invalid_frame"
            raise

    def _ingest(self, kind: str, frame: dict[str, Any], at: float) -> None:
        generation = int(frame["generation"])
        if generation < self.generation:
            return
        if generation > self.generation or kind == "spot_status":
            self.bids.clear()
            self.asks.clear()
            self.u = 0
            self.at = self.exchange_at = 0.0
            self.received_mono = None
            self.generation = generation
            self.status = str(frame.get("status", "awaiting_snapshot"))
        if kind != "spot_book":
            return
        data = frame["data"]
        if data["s"] != self.symbol:
            raise ValueError("spot_symbol_mismatch")
        u = int(data["u"])
        snapshot = frame.get("type") == "snapshot" or u == 1
        if not snapshot and (not self.u or u <= self.u):
            return
        stamp = float(frame["ts"]) / 1000
        if not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("spot_timestamp_invalid")
        if not snapshot and stamp < self.exchange_at:
            raise ValueError("spot_timestamp_regressed")
        if snapshot:
            self.bids.clear()
            self.asks.clear()
        for key, book in (("b", self.bids), ("a", self.asks)):
            for p, q in data.get(key, []):
                price, qty = float(p), float(q)
                if not math.isfinite(price * qty + price + qty) or price <= 0 or qty < 0:
                    raise ValueError("spot_level_invalid")
                if qty:
                    book[price] = qty
                else:
                    book.pop(price, None)
        self.u, self.at, self.exchange_at = u, at, stamp
        self.received_mono = frame.get("_received_monotonic")
        if not book_metrics(self.bids, self.asks)["valid"]:
            self.u = 0
            self.status = "invalid_book"
            raise ValueError("spot_book_crossed_or_empty")
        self.status = "streaming"

    def snapshot(self) -> dict[str, Any]:
        return {
            **book_metrics(self.bids, self.asks),
            "symbol": self.symbol,
            "category": "spot",
            "generation": self.generation,
            "status": self.status,
            "book_at": self.at,
            "exchange_at": self.exchange_at,
            "received_monotonic": self.received_mono,
        }


def entry_check(
    cross: dict[str, Any],
    side: int,
    at: float,
    config: Config,
    *,
    monotonic_at: float | None = None,
    symbol: str | None = None,
) -> str:
    """A conservative veto, not a fitted claim of predictive profitability."""
    for venue in (("spot", "linear") if config.requires_spot(symbol) else ("linear",)):
        book = cross.get(venue, {})
        if not book.get("valid") or (venue == "spot" and book.get("status") != "streaming"):
            return venue + "_not_ready"
        stamps = [book.get("book_at"), book.get("exchange_at")]
        if any(
            not isinstance(stamp, (float, int)) or not 0 <= at - stamp <= config.max_data_age_s
            for stamp in stamps
        ):
            return venue + "_stale"
        if monotonic_at is not None:
            receipt = book.get("received_monotonic")
            if not isinstance(receipt, (int, float)) or not (
                0 <= monotonic_at - receipt <= config.max_data_age_s
            ):
                return venue + "_stale_elapsed"
        if book["spread_bps"] > config.max_spread_bps:
            return venue + "_spread_wide"
        if side and side * book["imbalance"] < 0:
            return venue + "_pressure_opposes_entry"
    return "ready"
