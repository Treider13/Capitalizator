"""0.3.4 — taker side is the exchange print. We do not invent it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from capitalizator.book.reconstruct import Book
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Zone

TakerSide = Literal["buy", "sell"]

# PHASE-BUILD glossary: start ≥50% of depth_near on the zone side.
# Not a registry.yaml knob — the freeze rejects extra keys.
EATEN_SHARE = Decimal("0.5")


class TapeClassifier:
    def taker_side(self, trade: MarketEvent) -> TakerSide:
        if trade.stream != "trades":
            raise ValueError("taker_side expects stream=trades")
        side = str(trade.payload.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            raise ValueError(f"unknown taker side: {side!r}")
        return side

    def eaten(
        self,
        *,
        book: Book,
        trades: Sequence[MarketEvent],
        zone: Zone,
        t0: datetime,
        tick_size: Decimal,
        config: RegistryConfig | None = None,
    ) -> bool:
        """True if takers in the touch window lifted ≥50% of zone-side depth.

        Window is [t0, t0 + zlg_window_s] — the same 8s as the touch, not a 5-minute CVD.
        gap / book_diff / other streams in that window are not prints — skip them.
        No book / not ready → error (do not invent False).
        depth_near ticks = prs_delta_ticks from the freeze.
        """
        if not book.ready:
            raise ValueError("eaten needs a ready book")
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        cfg = config or load_registry()
        side = "bid" if zone.side == "support" else "ask"
        center = (zone.lo + zone.hi) / 2
        d_pre = book.depth_near(side, str(center), cfg.prs_delta_ticks)
        taken = self.eaten_qty(
            book=book,
            trades=trades,
            zone=zone,
            t0=t0,
            tick_size=tick_size,
            config=cfg,
        )
        if d_pre <= 0:
            return False
        return taken >= EATEN_SHARE * d_pre

    def eaten_qty(
        self,
        *,
        book: Book,
        trades: Sequence[MarketEvent],
        zone: Zone,
        t0: datetime,
        tick_size: Decimal,
        config: RegistryConfig | None = None,
    ) -> Decimal:
        """Taken zone-side qty in the 8s window. 0 if the book has no depth."""
        if not book.ready:
            raise ValueError("eaten needs a ready book")
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        cfg = config or load_registry()
        start = require_utc(t0)
        end = start + timedelta(seconds=cfg.zlg_window_s)
        pad = tick_size * cfg.epsilon_ticks
        side = "bid" if zone.side == "support" else "ask"
        want: TakerSide = "sell" if side == "bid" else "buy"
        center = (zone.lo + zone.hi) / 2
        d_pre = book.depth_near(side, str(center), cfg.prs_delta_ticks)
        if d_pre <= 0:
            return Decimal("0")
        taken = Decimal("0")
        lo, hi = zone.lo - pad, zone.hi + pad
        for trade in trades:
            if trade.stream != "trades":
                continue
            if trade.symbol != zone.symbol:
                continue
            ts = require_utc(trade.exchange_ts)
            if ts < start or ts > end:
                continue
            if self.taker_side(trade) != want:
                continue
            px = Decimal(str(trade.payload["px"]))
            if px < lo or px > hi:
                continue
            taken += Decimal(str(trade.payload["qty"]))
        return taken
