"""0.3.6 — Zone Liquidity Gesture. Log only. No size.

INVENTION-FIRST-FACT.md: four add buckets in (t, t+T], T = zlg_window_s.
SILENCE if max A < γ·q or the argmax is a tie.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from capitalizator.memory.registry import Touch
from capitalizator.types import require_utc
from capitalizator.zones.config import RegistryConfig, load_registry

Gesture = Literal["DEFEND", "RETREAT", "IMPROVE", "FADE", "SILENCE"]
BookSide = Literal["bid", "ask"]


@dataclass(frozen=True)
class BookAdd:
    ts: datetime
    side: BookSide
    px: Decimal
    qty: Decimal

    def __post_init__(self) -> None:
        require_utc(self.ts)
        if self.qty <= 0:
            raise ValueError("add qty must be > 0")


@dataclass(frozen=True)
class GestureResult:
    gesture: Gesture
    a_same: Decimal
    a_back: Decimal
    a_in: Decimal
    a_opp: Decimal


class ZLG:
    def __init__(self, *, tick_size: Decimal, config: RegistryConfig | None = None) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        self.tick_size = tick_size
        self.config = config or load_registry()

    def classify(
        self,
        touch: Touch,
        book_adds: Sequence[BookAdd],
        q: Decimal,
        *,
        hit_side: BookSide,
        mid: Decimal,
        opp_best: Decimal,
        book_ready: bool = True,
    ) -> GestureResult:
        if q <= 0:
            raise ValueError("q must be > 0")
        if (not book_ready) or mid == touch.trade_px:
            return GestureResult(
                gesture="SILENCE",
                a_same=Decimal("0"),
                a_back=Decimal("0"),
                a_in=Decimal("0"),
                a_opp=Decimal("0"),
            )
        t0 = require_utc(touch.ts)
        t1 = t0 + timedelta(seconds=self.config.zlg_window_s)
        a_same = a_back = a_in = a_opp = Decimal("0")
        one = self.tick_size
        delta = self.tick_size * self.config.prs_delta_ticks
        opp: BookSide = "ask" if hit_side == "bid" else "bid"
        for add in book_adds:
            ts = require_utc(add.ts)
            if ts <= t0 or ts > t1:
                continue
            if add.side == opp:
                if abs(add.px - opp_best) <= delta:
                    a_opp += add.qty
                continue
            if add.side != hit_side:
                continue
            if abs(add.px - touch.trade_px) <= one:
                a_same += add.qty
                continue
            toward_mid = (add.px - touch.trade_px) * (mid - touch.trade_px)
            if toward_mid > 0:
                a_in += add.qty
            else:
                a_back += add.qty
        buckets = {
            "DEFEND": a_same,
            "RETREAT": a_back,
            "IMPROVE": a_in,
            "FADE": a_opp,
        }
        peak = max(buckets.values())
        winners = [name for name, value in buckets.items() if value == peak]
        gamma_q = Decimal(str(self.config.zlg_gamma)) * q
        gesture: Gesture = "SILENCE"
        if peak >= gamma_q and len(winners) == 1:
            gesture = winners[0]
        return GestureResult(
            gesture=gesture,
            a_same=a_same,
            a_back=a_back,
            a_in=a_in,
            a_opp=a_opp,
        )
