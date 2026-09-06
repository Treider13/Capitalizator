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
from capitalizator.fusion.cross_market import SpotBook, book_metrics
from capitalizator.fusion.daily import daily_context
from capitalizator.fusion.flow import Flow
from capitalizator.fusion.structure import TFS, TRADE_TFS, Structure, candle, parse_history
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


def compact_profile(hist: dict[float, float], bins: int = 64) -> list[list[float]]:
    """Display-only aggregation; exact-print bins still determine POC/VAH/VAL."""
    if not hist:
        return []
    low, high = min(hist), max(hist)
    width = (high - low) / bins
    if not width:
        return [[low, sum(hist.values())]]
    aggregate: dict[int, float] = defaultdict(float)
    for price, volume in hist.items():
        aggregate[min(bins - 1, int((price - low) / width))] += volume
    return [[low + (i + 0.5) * width, volume] for i, volume in sorted(aggregate.items())]


def session_key(at: float) -> str:
    dt = datetime.fromtimestamp(at, UTC)
    # Contiguous UTC research buckets. London/New York local sessions live in legacy context.
    slot = "asia" if dt.hour < 8 else "europe" if dt.hour < 13 else "us" if dt.hour < 21 else "late"
    return f"{dt.date()}:{slot}"


class Market:
    def __init__(self, symbol: str, config: Config, tick: float = 0.1) -> None:
        self.symbol, self.config, self.tick = symbol, config, tick
        self.spot = SpotBook(symbol)
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.book_u = 0
        self.book_at = 0.0
        self.book_exchange_at: float | None = None
        self.book_received_mono: float | None = None
        self.trade_at = 0.0
        self.ticker_at = 0.0
        self.valid = False
        self.ticker: dict[str, Any] = {}
        self.blocks: deque[Block] = deque(maxlen=config.context_blocks * 4)
        self.pending = Flow()
        self.amd_phase = "unclassified"
        self.amd_side = 0
        self.amd_origin = 0
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
        self.previous_profile: dict[str, Any] = {}
        self.observation_start = 0.0
        self.profile_complete = False
        self.builder = BarBuilder(symbol, TRADE_TFS)
        self.structure = Structure()
        self.chart_cache: dict[str, Any] = {}
        self.chart_revision = -1
        self.block_cache: dict[str, Any] | None = None
        self.forming_cache: dict[str, Any] = {}
        self.forming_dirty = True
        self.analytics_cache: list[dict[str, Any]] = []
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
        self.book_exchange_at = None
        self.book_received_mono = None
        self.pending.clear()
        self.amd_phase, self.amd_side, self.amd_origin = "unclassified", 0, 0
        self.blocks.clear()
        self.refill = self.liquidations = 0.0
        self.builder = BarBuilder(self.symbol, TRADE_TFS)
        self.structure = Structure()
        self.chart_cache = {}
        self.chart_revision = -1
        self.block_cache = None
        self.analytics_cache = []
        self.forming_cache = {}
        self.forming_dirty = True
        self.bars.clear()
        self.hist.clear()
        self.previous_profile = {}
        self.observation_start = 0.0
        self.profile_complete = False
        self.session = ""
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
        stamp = float(frame["ts"]) / 1000 if frame.get("ts") is not None else None
        if stamp is not None and (
            not math.isfinite(stamp)
            or stamp <= 0
            or (
                not snapshot and self.book_exchange_at is not None and stamp < self.book_exchange_at
            )
        ):
            self.reset()
            raise ValueError("invalid_or_regressed_futures_timestamp")
        if snapshot:
            if not self.book_u:
                self.observation_start = at
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
        self.book_exchange_at = stamp
        self.book_received_mono = frame.get("_received_monotonic")
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
            if not 0 <= at - exch <= self.config.max_data_age_s:
                raise ValueError("trade_timestamp_outside_receipt_window")
            if exch < self.last_exchange_trade:
                self.late_trades += 1
                continue  # Never rewrite a finished contract/bar.
            self.last_exchange_trade = exch
            px, qty = float(raw["p"]), float(raw["v"])
            sign = 1 if raw["S"] == "Buy" else -1
            self.trade_at = at
            self.cvd += qty * sign
            self.builder.on_trade(event)
            self.forming_dirty = True
            for bar in self.builder.close_due(event.exchange_ts):
                self.structure.add(bar, self.tick)
                if bar.tf == "1m":
                    self.bars.append(bar)
            key = session_key(exch)
            if key != self.session:
                self.previous_profile = {**profile(self.hist), "complete": self.profile_complete}
                dt = datetime.fromtimestamp(exch, UTC)
                hour = 0 if dt.hour < 8 else 8 if dt.hour < 13 else 13 if dt.hour < 21 else 21
                start = dt.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()
                self.profile_complete = bool(
                    self.observation_start and self.observation_start <= start
                )
                self.hist.clear()
                self.session = key
            self.hist[round(px / self.tick) * self.tick] += qty
            active = sessions(exch)
            for name in list(self.named_dates):
                if active.get(name) != self.named_dates[name]:
                    histogram = self.named_hist.pop(name)
                    self.named_previous[name] = {
                        **profile(histogram),
                        "histogram": compact_profile(histogram),
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
            if raw.get("BT") is True:
                self.pending.block_volume += qty
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
        volume = self.pending.volume
        flow = self.pending.delta / volume
        close, high, low = self.pending.close, self.pending.high, self.pending.low
        history = list(self.blocks)[-self.config.context_blocks :]
        returns = [b.x[0] for b in history]
        vol = max(float(np.std(returns)) if returns else 0, self.tick / close)
        prev = history[-1].close if history else self.pending.open
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
        gaps = [i for i in range(1, len(bars)) if bars[i].open_ts != bars[i - 1].close_ts]
        if gaps:
            bars = bars[gaps[-1] :]
        if bars and bars[-1].close_ts != self.geometry_at:
            self.geometry = geometry(bars, self.tick)
            self.geometry_at = bars[-1].close_ts
        bos = bos_status(bars)
        choch = bos if bos and self.last_bos and bos != self.last_bos else None
        if bos:
            self.last_bos = bos
        fvg = latest_fvg(bars) if bars else None
        ranges = [float(b.high - b.low) for b in bars[-14:]]
        pairing = self.structure.pair(sweep, close, low, high, at) if sweep else {"allowed": False}
        if sweep:
            self.amd_phase, self.amd_side, self.amd_origin = "manipulation", sweep, self.block_id
        elif (
            self.amd_side
            and self.block_id - self.amd_origin <= self.config.horizon_blocks
            and self.amd_side * x[0] > 0
            and self.amd_side * flow > 0
        ):
            self.amd_phase = "distribution"
        elif (
            history
            and abs(x[0]) <= float(np.median([abs(b.x[0]) for b in history]))
            and abs(flow) <= float(np.median([abs(b.flow) for b in history]))
            and volume >= float(np.median([b.volume for b in history]))
        ):
            self.amd_phase = "accumulation"
            self.amd_side = 0
        else:
            self.amd_phase = "unclassified"
        context = {
            "largest_print": self.pending.largest,
            "block_trade_volume": self.pending.block_volume,
            "pairing": pairing,
            "daily": daily_context(self.structure.cache.get("1d", {}), close, at),
            "support": support,
            "resistance": resistance,
            "sweep": sweep,
            "sweep_extreme": low if sweep == 1 else high,
            "volatility": vol,
            "atr": float(np.mean(ranges)) if ranges else vol * close,
            "depth": depth,
            "bid_depth": bidq,
            "ask_depth": askq,
            "bid": max(self.bids),
            "ask": min(self.asks),
            "profile": self.previous_profile,
            "session": self.session,
            "bos": bos,
            "choch": choch,
            "geometry": self.geometry,
            "session_profiles": dict(self.named_previous),
            "volume_percentile": rank(volume, [b.volume for b in history]),
            "oi_change_percentile": rank(abs(doi), [abs(b.x[5]) for b in history]),
            "replenishment_absorption": absorption(flow, refill, x[0], vol),
            "order_block": ob_status(bars),
            "fvg": [float(v) for v in fvg] if fvg else None,
            "discount": (close - support) / span,
            "ote_long": [resistance - 0.786 * span, resistance - 0.618 * span],
            "ote_short": [support + 0.618 * span, support + 0.786 * span],
            "amd": self.amd_phase,
            "amd_definition": "sweep / subsequent flow / median compression; intent unobserved",
            "cvd": self.cvd,
            "at": at,
            "book_at": self.book_at,
            "ticker_at": self.ticker_at,
            "cross_market": self.cross_market(),
            "mark": self.ticker.get("markPrice"),
            "funding": float(self.ticker.get("fundingRate") or 0),
        }
        if self.geometry.get("atr") is not None:
            context["atr"] = self.geometry["atr"]
        block = Block(
            self.block_id,
            at,
            self.pending_start,
            self.pending.open,
            high,
            low,
            close,
            volume,
            flow,
            refill,
            x,
            context,
        )
        self.block_cache = asdict(block)
        self.analytics_cache = [
            {
                "at": b.at,
                "cvd": b.context["cvd"],
                "flow": b.flow,
                "volume": b.volume,
                "oi_change": b.x[5],
                "liquidations": b.x[6],
            }
            for b in [*self.blocks, block][-self.config.context_blocks * 4 :]
        ]
        self.pending.clear()
        self.refill = self.liquidations = 0.0
        return block

    def snapshot(self) -> dict[str, Any]:
        if self.chart_revision != self.structure.revision:
            self.chart_cache = dict(self.structure.cache)
            self.chart_revision = self.structure.revision
        if self.forming_dirty:
            self.forming_cache = {
                tf: candle(b) for tf in TFS if (b := self.builder.open_bucket(tf)) is not None
            }
            self.forming_dirty = False
        return {
            "chart": self.chart_cache,
            "chart_revision": self.chart_revision,
            "forming": self.forming_cache,
            "analytics": self.analytics_cache,
            "symbol": self.symbol,
            "valid": self.valid,
            "book_at": self.book_at,
            "ticker_at": self.ticker_at,
            "trade_at": self.trade_at,
            "late_trades": self.late_trades,
            "cross_market": self.cross_market(),
            "spot_levels": {
                "bids": sorted(self.spot.bids.items(), reverse=True)[:20],
                "asks": sorted(self.spot.asks.items())[:20],
            },
            "block": self.block_cache,
            "bid": max(self.bids) if self.bids else None,
            "ask": min(self.asks) if self.asks else None,
            "book_levels": {
                "bids": sorted(self.bids.items(), reverse=True)[:20],
                "asks": sorted(self.asks.items())[:20],
            },
        }

    def cross_market(self) -> dict[str, Any]:
        spot = self.spot.snapshot()
        linear = {
            **book_metrics(self.bids, self.asks),
            "book_at": self.book_at,
            "exchange_at": self.book_exchange_at,
            "received_monotonic": self.book_received_mono,
        }
        linear["valid"] = bool(linear["valid"] and self.valid)
        ready = spot["valid"] and linear["valid"]
        return {
            "spot": spot,
            "linear": linear,
            "basis_bps": (linear["mid"] / spot["mid"] - 1) * 10000 if ready else None,
            "imbalance_gap": linear["imbalance"] - spot["imbalance"] if ready else None,
            "opposed": spot["imbalance"] * linear["imbalance"] < 0 if ready else None,
        }

    def ingest(self, kind: str, frame: dict[str, Any], at: float) -> list[Block]:
        if kind.startswith("spot_"):
            self.spot.ingest(kind, frame, at)
        elif kind == "book":
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
        elif kind == "history":
            bars = parse_history(
                self.symbol, frame["tf"], frame["rows"], min(at, float(frame.get("known_at", at)))
            )
            self.structure.seed(bars, self.tick)
            self.builder.seed_closed(bars)
            self.bars = deque(self.structure.bars["1m"], maxlen=256)
            self.geometry_at = None  # REST can repair history without advancing its last bar.
        elif kind == "gap":
            self.reset()
        return []
