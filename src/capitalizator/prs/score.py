"""0.3.5 — Passive Replenishment Score. Log only. No order.

PASSIVE-RESILIENCE.md:
  τ until depth_near returns to α·D_pre, else T_max (censored).
  X = log(1 + τ / (1 + λ q / D_pre)), λ=1.
  Y = robust z of EWMA(X) vs median/MAD of the last W events (need ≥30).

Does not place an order to measure the book.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from capitalizator.book.reconstruct import Book
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zones.config import RegistryConfig, load_registry

LAMBDA_Q = Decimal("1")
BETA_EWMA = Decimal("0.15")
Y_MIN_N = 30
W = 400
EPS = Decimal("1e-9")


@dataclass(frozen=True)
class PRSResult:
    tau: Decimal
    X: Decimal
    Y: Decimal | None
    censored: bool
    d_pre: Decimal


class PRS:
    def __init__(self, *, tick_size: Decimal, config: RegistryConfig | None = None) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        self.tick_size = tick_size
        self.config = config or load_registry()
        self.x_ewma: Decimal | None = None
        self.xs: deque[Decimal] = deque(maxlen=W)
        self.log: list[PRSResult] = []

    def compute(
        self,
        trade: MarketEvent,
        book_pre: Book,
        book_path: Sequence[tuple[datetime, Book]],
    ) -> PRSResult:
        if not book_pre.ready:
            raise ValueError("PRS needs a ready book_pre")
        side = TapeClassifier().taker_side(trade)
        hit = "bid" if side == "sell" else "ask"
        px = str(trade.payload["px"])
        qty = Decimal(str(trade.payload["qty"]))
        if qty <= 0:
            raise ValueError("trade qty must be > 0")
        d_pre = book_pre.depth_near(hit, px, self.config.prs_delta_ticks)
        if d_pre <= 0:
            raise ValueError("D_pre must be > 0")
        t0 = require_utc(trade.exchange_ts)
        deadline = t0 + timedelta(seconds=self.config.prs_t_max_s)
        target = Decimal(str(self.config.prs_alpha)) * d_pre
        recovered_at: datetime | None = None
        prev_ts = t0
        for ts, book in book_path:
            when = require_utc(ts)
            if when < prev_ts:
                raise ValueError("book_path timestamps must be non-decreasing")
            prev_ts = when
            if when <= t0:
                continue
            if when > deadline:
                break
            if not book.ready:
                raise ValueError("PRS book_path needs ready books")
            if book.depth_near(hit, px, self.config.prs_delta_ticks) >= target:
                recovered_at = when
                break
        if recovered_at is None:
            tau = Decimal(self.config.prs_t_max_s)
            censored = True
        else:
            tau = Decimal(str((recovered_at - t0).total_seconds()))
            censored = False
        xi = (Decimal("1") + tau / (Decimal("1") + LAMBDA_Q * qty / d_pre)).ln()
        if self.x_ewma is None:
            self.x_ewma = xi
        else:
            self.x_ewma = (Decimal("1") - BETA_EWMA) * self.x_ewma + BETA_EWMA * xi
        self.xs.append(self.x_ewma)
        result = PRSResult(tau=tau, X=xi, Y=self.y(), censored=censored, d_pre=d_pre)
        self.log.append(result)
        return result

    def y(self) -> Decimal | None:
        if self.x_ewma is None or len(self.xs) < Y_MIN_N:
            return None
        xs = sorted(self.xs)
        med = xs[len(xs) // 2]
        mad = sorted(abs(v - med) for v in xs)[len(xs) // 2]
        return (self.x_ewma - med) / (mad if mad > 0 else EPS)
