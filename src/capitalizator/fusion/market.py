"""Receipt-time market state and trade-count blocks. One owner per symbol."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from capitalizator.card.smc import bos_status, ob_status
from capitalizator.desk.bars import BarBuilder
from capitalizator.exec.fvg_mark import latest_fvg
from capitalizator.fusion.config import Config
from capitalizator.fusion.context import absorption, geometry, rank, sessions
from capitalizator.recorder.normalize import normalize_bybit_public_trade

FEATURES = (
    "return",
    "flow",
    "book_imbalance",
    "spread",
    "refill",
    "oi_change",
    "liquidations",
    "location",
    "sweep",
    "volatility",
    "duration",
    "volume",
)


@dataclass(frozen=True)
class Block:
    id: int
    at: float
    start: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    flow: float
    refill: float
    x: tuple[float, ...]
    context: dict[str, Any]


def profile(hist: dict[float, float], fraction: float = 0.7) -> dict[str, float]:
    if not hist:
        return {}
    points = sorted(hist)
    peak = max(range(len(points)), key=lambda i: hist[points[i]])
    lo = hi = peak
    total = hist[points[peak]]
    target = sum(hist.values()) * fraction
    while total < target and (lo > 0 or hi < len(points) - 1):
        left = hist[points[lo - 1]] if lo else -1
        right = hist[points[hi + 1]] if hi + 1 < len(points) else -1
        if left >= right:
            lo -= 1
            total += hist[points[lo]]
        else:
            hi += 1
            total += hist[points[hi]]
    return {"poc": points[peak], "val": points[lo], "vah": points[hi]}


def session_key(at: float) -> str:
    dt = datetime.fromtimestamp(at, UTC)
    # Contiguous UTC research buckets. London/New York local sessions live in legacy context.
    slot = "asia" if dt.hour < 8 else "europe" if dt.hour < 13 else "us" if dt.hour < 21 else "late"
    return f"{dt.date()}:{slot}"


class Market:
    def __init__(self, symbol: str, config: Config, tick: float = 0.1) -> None:
        self.symbol, self.config, self.tick = symbol, config, tick
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.book_u = 0
        self.book_at = 0.0
        self.trade_at = 0.0
        self.ticker_at = 0.0
        self.valid = False
        self.ticker: dict[str, Any] = {}
        self.blocks: deque[Block] = deque(maxlen=config.context_blocks * 4)
        self.pending: list[tuple[float, float, int]] = []
        self.pending_start = 0.0
        self.block_id = 0
        self.refill = 0.0
        self.liquidations = 0.0
        self.old_oi = 0.0
        self.cvd = 0.0
        self.ids: set[str] = set()
        self.id_queue: deque[str] = deque()
        self.hist: dict[float, float] = defaultdict(float)
        self.session = ""
        self.previous_profile: dict[str, float] = {}
        self.builder = BarBuilder(symbol, ("1m", "5m"))
        self.bars: deque[Any] = deque(maxlen=256)
        self.last_exchange_trade = 0.0
        self.late_trades = 0
        self.named_hist: dict[str, dict[float, float]] = {}
        self.named_dates: dict[str, str] = {}
        self.named_previous: dict[str, Any] = {}
        self.geometry: dict[str, Any] = {}
        self.geometry_at: Any = None
        self.last_bos: str | None = None

    def reset(self) -> None:
        self.valid = False
        self.book_u = 0
        self.pending.clear()
        self.blocks.clear()
        self.refill = self.liquidations = 0.0
        self.builder = BarBuilder(self.symbol, ("1m", "5m"))
        self.bars.clear()
        self.hist.clear()
        self.previous_profile = {}
        self.named_hist.clear()
        self.named_dates.clear()
        self.named_previous.clear()
        self.geometry, self.geometry_at, self.last_bos = {}, None, None

    def book(self, frame: dict[str, Any], at: float) -> None:
        data = frame["data"]
        u = int(data["u"])
        snapshot = frame.get("type") == "snapshot" or u == 1
        if not snapshot and (not self.valid or u <= self.book_u):
            return
        if snapshot:
            self.bids.clear()
            self.asks.clear()
        for key, book, sign in (("b", self.bids, 1), ("a", self.asks, -1)):
            for p, q in data.get(key, []):
                px, qty = float(p), float(q)
                if not math.isfinite(px + qty) or px <= 0 or qty < 0:
                    self.reset()
                    raise ValueError("invalid book level")
                if not snapshot:
                    self.refill += sign * max(0.0, qty - book.get(px, 0.0))
                if qty:
                    book[px] = qty
                else:
                    book.pop(px, None)
        self.book_u, self.book_at = u, at
        self.valid = bool(self.bids and self.asks and max(self.bids) < min(self.asks))

    def trades(self, frame: dict[str, Any], at: float) -> list[Block]:
        out = []
        for raw in frame["data"]:
            ident = str(raw.get("i") or "")
            if not ident:
                raise ValueError("trade id required")
            if ident in self.ids:
                continue
            self.ids.add(ident)
            self.id_queue.append(ident)
            if len(self.id_queue) > 100000:
                self.ids.remove(self.id_queue.popleft())
            event = normalize_bybit_public_trade(raw, recv_ts=datetime.fromtimestamp(at, UTC))
            exch = event.exchange_ts.timestamp()
            if exch < self.last_exchange_trade:
                self.late_trades += 1
                continue  # Never rewrite a finished contract/bar.
            self.last_exchange_trade = exch
            px, qty = float(raw["p"]), float(raw["v"])
            sign = 1 if raw["S"] == "Buy" else -1
            self.trade_at = at
            self.cvd += qty * sign
            self.builder.on_trade(event)
            for bar in self.builder.close_due(datetime.fromtimestamp(at, UTC)):
                if bar.tf == "1m":
                    self.bars.append(bar)
            key = session_key(exch)
            if key != self.session:
                self.previous_profile = profile(self.hist)
                self.hist.clear()
                self.session = key
            self.hist[round(px / self.tick) * self.tick] += qty
            active = sessions(exch)
            for name in list(self.named_dates):
                if active.get(name) != self.named_dates[name]:
                    self.named_previous[name] = {
                        **profile(self.named_hist.pop(name)),
                        "date": self.named_dates.pop(name),
                        "coverage": "observed prints; first session can be partial",
                    }
            for name, date in active.items():
                self.named_dates[name] = date
                histogram = self.named_hist.setdefault(name, {})
                price_bin = round(px / self.tick) * self.tick
                histogram[price_bin] = histogram.get(price_bin, 0) + qty
            if not self.valid:
                continue
            if not self.pending:
                self.pending_start = at
            self.pending.append((px, qty, sign))
            elapsed = at - self.pending_start
            if (
                len(self.pending) >= self.config.block_trades
                and elapsed >= self.config.block_seconds
            ) or elapsed >= self.config.block_max_seconds:
                block = self._finish(at)
                self.blocks.append(block)
                out.append(block)
        return out

    def _finish(self, at: float) -> Block:
        self.block_id += 1
        prices = [r[0] for r in self.pending]
        volume = sum(r[1] for r in self.pending)
        flow = sum(r[1] * r[2] for r in self.pending) / volume
        close, high, low = prices[-1], max(prices), min(prices)
        history = list(self.blocks)[-self.config.context_blocks :]
        returns = [b.x[0] for b in history]
        vol = max(float(np.std(returns)) if returns else 0, self.tick / close)
        prev = history[-1].close if history else prices[0]
        support = min((b.low for b in history), default=low)
        resistance = max((b.high for b in history), default=high)
        sweep = (
            1
            if history and low < support and close > support
            else (-1 if history and high > resistance and close < resistance else 0)
        )
        bidq = sum(v for _, v in sorted(self.bids.items(), reverse=True)[:50])
        askq = sum(v for _, v in sorted(self.asks.items())[:50])
        depth = bidq + askq
        oi = float(self.ticker.get("openInterest") or 0)
        doi = (oi - self.old_oi) / self.old_oi if self.old_oi else 0.0
        self.old_oi = oi
        refill = self.refill / max(volume, depth, 1e-12)
        span = max(resistance - support, self.tick)
        duration = max(at - self.pending_start, 0.001)
        x = (
            math.log(close / prev),
            flow,
            (bidq - askq) / max(depth, 1e-12),
            (min(self.asks) - max(self.bids)) / close,
            refill,
            doi,
            self.liquidations / max(volume, 1e-12),
            (close - support) / span,
            float(sweep),
            vol,
            math.log1p(duration),
            math.log1p(volume),
        )
        bars = list(self.bars)
        if bars and bars[-1].close_ts != self.geometry_at:
            self.geometry = geometry(bars, self.tick)
            self.geometry_at = bars[-1].close_ts
        bos = bos_status(bars)
        choch = bos if bos and self.last_bos and bos != self.last_bos else None
        if bos:
            self.last_bos = bos
        fvg = latest_fvg(bars) if bars else None
        ranges = [float(b.high - b.low) for b in bars[-14:]]
        context = {
            "support": support,
            "resistance": resistance,
            "sweep": sweep,
            "sweep_extreme": low if sweep == 1 else high,
            "volatility": vol,
            "atr": float(np.mean(ranges)) if ranges else vol * close,
            "depth": depth,
            "bid": max(self.bids),
            "ask": min(self.asks),
            "profile": self.previous_profile,
            "session": self.session,
            "bos": bos_status(bars),
            "choch": choch,
            "geometry": self.geometry,
            "session_profiles": dict(self.named_previous),
            "volume_percentile": rank(volume, [b.volume for b in history]),
            "oi_change_percentile": rank(abs(doi), [abs(b.x[5]) for b in history]),
            "replenishment_absorption": absorption(flow, refill, x[0], vol),
            "gamma_exposure": None,
            "gamma_status": "options positions and dealer sign unavailable",
            "order_block": ob_status(bars),
            "fvg": [float(v) for v in fvg] if fvg else None,
            "discount": (close - support) / span,
            "ote_long": [resistance - 0.786 * span, resistance - 0.618 * span],
            "ote_short": [support + 0.618 * span, support + 0.786 * span],
            "amd": "manipulation"
            if sweep
            else ("distribution" if abs(x[0]) > vol and abs(flow) > 0.5 else "accumulation"),
            "cvd": self.cvd,
            "at": at,
            "book_at": self.book_at,
            "ticker_at": self.ticker_at,
            "mark": self.ticker.get("markPrice"),
            "funding": float(self.ticker.get("fundingRate") or 0),
        }
        if self.geometry.get("atr") is not None:
            context["atr"] = self.geometry["atr"]
        block = Block(
            self.block_id,
            at,
            self.pending_start,
            prices[0],
            high,
            low,
            close,
            volume,
            flow,
            refill,
            x,
            context,
        )
        self.pending.clear()
        self.refill = self.liquidations = 0.0
        return block

    def snapshot(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "valid": self.valid,
            "book_at": self.book_at,
            "ticker_at": self.ticker_at,
            "trade_at": self.trade_at,
            "late_trades": self.late_trades,
            "block": asdict(self.blocks[-1]) if self.blocks else None,
            "bid": max(self.bids) if self.bids else None,
            "ask": min(self.asks) if self.asks else None,
        }

    def ingest(self, kind: str, frame: dict[str, Any], at: float) -> list[Block]:
        if kind == "book":
            self.book(frame, at)
        elif kind == "trades":
            return self.trades(frame, at)
        elif kind == "ticker":
            self.ticker.update(frame["data"])
            self.ticker_at = at
        elif kind == "liquidation":
            for row in frame.get("data", []):
                # Bybit S is the liquidated position side, not the aggressor side.
                self.liquidations += float(row["v"]) * (-1 if row["S"] == "Buy" else 1)
        elif kind == "gap":
            self.reset()
        return []
