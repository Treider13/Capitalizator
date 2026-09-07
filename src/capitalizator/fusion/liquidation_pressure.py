"""Receipt-causal, bounded liquidation observer. Never authorizes or sends orders.

Bybit allLiquidation S is the position side and p is bankruptcy price. Its rows
have no execution ID; equal-looking liquidations are deliberately not deduped.
Thresholds are versioned research settings, not calibrated trading probabilities.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any


@dataclass(frozen=True)
class PressureConfig:
    mode: str = "observe"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    warmup_s: float = 3600.0
    baseline_windows: int = 720
    min_baseline_windows: int = 60
    minimum_liquidation_usd: float = 100000.0
    minimum_traded_usd: float = 50000.0
    anomaly_multiple: float = 4.0
    movement_bps: float = 5.0
    confirmation_s: float = 10.0
    deadline_s: float = 120.0
    normalization_s: float = 60.0
    max_age_s: float = 5.0
    sample_s: float = 1.0
    journal_s: float = 30.0

    def __post_init__(self) -> None:
        if self.mode not in {"off", "observe"}:
            raise ValueError(
                "pressure supports off/observe only; execution filtering is not enabled"
            )
        if not self.symbols or any(s not in {"BTCUSDT", "ETHUSDT"} for s in self.symbols):
            raise ValueError("pressure v1 supports BTCUSDT and ETHUSDT only")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("duplicate pressure symbols")
        for key, value in asdict(self).items():
            if key in {"mode", "symbols"}:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"invalid pressure {key}")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"invalid pressure {key}")
        if not isinstance(self.baseline_windows, int) or not isinstance(
            self.min_baseline_windows, int
        ):
            raise ValueError("baseline counts must be integers")
        if not 2 <= self.min_baseline_windows <= self.baseline_windows <= 10080:
            raise ValueError("invalid baseline limits")
        if self.warmup_s < 120 or not 0.5 <= self.sample_s <= 5:
            raise ValueError("warmup >=120s and sample 0.5..5s required")
        if self.max_age_s < self.sample_s:
            raise ValueError("freshness must cover the calculation period")
        if self.confirmation_s >= self.deadline_s or self.anomaly_multiple <= 1:
            raise ValueError("invalid confirmation/anomaly settings")

    @property
    def version(self) -> str:
        body = {"algorithm": "liquidation-observer-3", **asdict(self)}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:20]

    @classmethod
    def load(cls, path: Path) -> PressureConfig:
        if not path.exists():
            return cls()
        body = json.loads(path.read_text())
        if not isinstance(body, dict):
            raise ValueError("pressure config must be an object")
        if "symbols" in body:
            if not isinstance(body["symbols"], list):
                raise ValueError("pressure symbols must be a list")
            body["symbols"] = tuple(body["symbols"])
        return cls(**body)


@dataclass
class Bucket:
    at: int
    buys: float = 0.0
    sells: float = 0.0
    long_liquidations: float = 0.0
    short_liquidations: float = 0.0
    trades: int = 0
    low: float = math.inf
    high: float = 0.0
    first: float = 0.0
    last: float = 0.0


@dataclass
class Episode:
    id: str
    direction: str
    started: float
    state: str
    extreme: float
    peak: float
    last_wave: float
    anchor: float | None = None
    checking_since: float | None = None
    normal_since: float | None = None
    depth_low: float | None = None
    depth_high: float | None = None
    depth_reference: float | None = None
    reason: str = "liquidations_flow_and_price"


class PressureObserver:
    """Owned by the symbol actor; snapshots contain JSON-safe copies only."""

    def __init__(self, symbol: str, config: PressureConfig | None = None) -> None:
        self.symbol, self.config = symbol, config or PressureConfig()
        self.version = self.config.version
        self.enabled = self.config.mode == "observe" and symbol in self.config.symbols
        self.generation = 0
        self.last_event_id = -1
        self.last_data_receipt: float | None = None
        self.last_receipt: float | None = None
        self.started: float | None = None
        self.last_eval = -math.inf
        self.valid_until: float | None = None
        self.last_journal = -math.inf
        self.signature: str | None = None
        self.error: str | None = None
        self.configuration_error: str | None = None
        self.buckets: deque[Bucket] = deque(maxlen=121)
        self.baseline: deque[tuple[float, float]] = deque(maxlen=self.config.baseline_windows)
        self.baseline_slot: int | None = None
        self.ids: set[str] = set()
        self.id_queue: deque[str] = deque()
        self.episodes: dict[str, Episode] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=20)
        self.last_trade_at: float | None = None
        self.last_trade_exchange = -math.inf
        self.metrics: dict[str, Any] = {}
        self.quality = "warming" if self.enabled else "off"
        self.reason = "collecting_baseline" if self.enabled else "observer_disabled"
        self.last_record: dict[str, Any] | None = None

    def reset(self, at: float, reason: str) -> None:
        for episode in self.episodes.values():
            self.history.append({**asdict(episode), "ended": at, "outcome": "data_gap"})
        self.episodes.clear()
        self.buckets.clear()
        self.baseline.clear()
        self.ids.clear()
        self.id_queue.clear()
        self.started = None
        self.last_trade_at = None
        self.last_trade_exchange = -math.inf
        self.baseline_slot = None
        self.metrics = {}
        self.generation += 1
        self.error = self.configuration_error
        self.quality, self.reason = (
            ("error", "configuration_error") if self.error else ("unavailable", reason)
        )
        self.last_eval = -math.inf
        self.valid_until = None

    def _lose_confirmation(self) -> None:
        for ep in self.episodes.values():
            ep.normal_since = None
            if ep.checking_since is not None or ep.state == "recovery":
                ep.state, ep.reason = "mixed", "confirmation_trade_continuity_lost"
                ep.checking_since = ep.anchor = None

    def fail(self, error: Exception) -> None:
        self.error = type(error).__name__ + ": " + str(error)[:160]
        self.quality, self.reason = "error", "observer_error"

    @staticmethod
    def _positive(value: Any) -> float:
        n = float(value)
        if not math.isfinite(n) or n <= 0:
            raise ValueError("nonpositive/nonfinite pressure value")
        return n

    def step(
        self, kind: str, frame: dict[str, Any], at: float, market: Any, *, event_id: int
    ) -> dict[str, Any] | None:
        if not self.enabled or event_id <= self.last_event_id:
            return None
        self.last_event_id = event_id
        if kind not in {"book", "trades", "liquidation", "ticker", "gap", "pressure_clock"}:
            return None
        if not math.isfinite(at):
            raise ValueError("invalid receipt time")
        if self.last_data_receipt is not None and at < self.last_data_receipt:
            if kind == "pressure_clock":
                return None
            self.last_data_receipt = at
            self.reset(at, "receipt_clock_regressed")
            self.last_receipt = at
            return self._record(at, force=True)
        self.last_receipt = at
        if kind != "pressure_clock":
            self.last_data_receipt = at
        if kind == "gap":
            self.reset(at, str(frame.get("reason", "data_gap")))
            return self._record(at, force=True)
        if self.error:
            return self._record(at)
        good_book = (
            market.valid
            and market.book_exchange_at is not None
            and 0 <= at - market.book_at <= self.config.max_age_s
            and 0 <= at - market.book_exchange_at <= self.config.max_age_s
        )
        if not good_book:
            if self.started is not None:
                self.reset(at, "book_unavailable")
            self.quality, self.reason = "unavailable", "book_unavailable"
            return self._record(at)
        if self.started is not None and at - self.last_eval > self.config.max_age_s:
            self.reset(at, "observation_gap")
        if self.started is None:
            self.started = at
        if self.last_trade_at is not None and at - self.last_trade_at > self.config.max_age_s:
            self._lose_confirmation()
            self.quality, self.reason = "unavailable", "insufficient_recent_trades"
        while self.buckets and self.buckets[0].at <= int(at) - 120:
            self.buckets.popleft()
        if not self.buckets or self.buckets[-1].at != int(at):
            self.buckets.append(Bucket(int(at)))
        bucket = self.buckets[-1]
        if kind == "trades":
            for row in frame["data"]:
                ident = str(row["i"])
                if ident in self.ids:
                    continue
                self.ids.add(ident)
                self.id_queue.append(ident)
                if len(self.id_queue) > 100000:
                    self.ids.remove(self.id_queue.popleft())
                exchange_at = self._positive(row["T"]) / 1000
                if not 0 <= at - exchange_at <= self.config.max_age_s:
                    self.reset(at, "late_trade")
                    return self._record(at, force=True)
                if exchange_at < self.last_trade_exchange:
                    self.reset(at, "trade_clock_regressed")
                    return self._record(at, force=True)
                self.last_trade_exchange = exchange_at
                price, qty = self._positive(row["p"]), self._positive(row["v"])
                if row["S"] not in {"Buy", "Sell"}:
                    raise ValueError("unknown trade side")
                value = price * qty
                if not math.isfinite(value):
                    raise ValueError("nonfinite trade notional")
                if row["S"] == "Buy":
                    bucket.buys += value
                else:
                    bucket.sells += value
                bucket.trades += 1
                bucket.first = bucket.first or price
                bucket.last = price
                bucket.low, bucket.high = min(bucket.low, price), max(bucket.high, price)
                self.last_trade_at = at
        elif kind == "liquidation":
            mid = (max(market.bids) + min(market.asks)) / 2
            # Stage the complete batch before mutation; p is never an execution price.
            values = []
            for row in frame["data"]:
                stamp = self._positive(row["T"]) / 1000
                if row["s"] != self.symbol or row["S"] not in {"Buy", "Sell"}:
                    raise ValueError("invalid liquidation symbol/side")
                if not 0 <= at - stamp <= self.config.max_age_s:
                    self.reset(at, "late_liquidation")
                    return self._record(at, force=True)
                value = self._positive(row["v"]) * mid
                if not math.isfinite(value):
                    raise ValueError("nonfinite liquidation notional")
                values.append((row["S"], value))
            for side, value in values:
                if side == "Buy":
                    bucket.long_liquidations += value
                else:
                    bucket.short_liquidations += value
        if kind == "book":
            # Invalidate on every observed update, including sub-sample quote flashes.
            for ep in self.episodes.values():
                if ep.checking_since is None:
                    continue
                depth = self._depth(market, ep)
                if depth is None or ep.depth_reference is None or depth < ep.depth_reference:
                    ep.state, ep.reason = "mixed", "confirmation_depth_lost"
                    ep.checking_since = ep.anchor = None
        if at - self.last_eval >= self.config.sample_s:
            self._evaluate(at, market)
        return self._record(at)

    def _window(self, at: float, seconds: int) -> dict[str, float]:
        rows = [b for b in self.buckets if int(at) - seconds < b.at <= int(at)]
        traded = [b for b in rows if b.trades]
        return {
            "buy_usd": sum(b.buys for b in rows),
            "sell_usd": sum(b.sells for b in rows),
            "long_liquidation_usd_estimate": sum(b.long_liquidations for b in rows),
            "short_liquidation_usd_estimate": sum(b.short_liquidations for b in rows),
            "trades": sum(b.trades for b in rows),
            "first": traded[0].first if traded else 0.0,
            "last": traded[-1].last if traded else 0.0,
            "low": min(b.low for b in traded) if traded else 0.0,
            "high": max(b.high for b in traded) if traded else 0.0,
        }

    def _threshold(self, index: int) -> float:
        values = sorted(row[index] for row in self.baseline)
        if not values:
            return self.config.minimum_liquidation_usd
        percentile = values[min(len(values) - 1, math.ceil(len(values) * 0.99) - 1)]
        return max(
            self.config.minimum_liquidation_usd,
            percentile,
            median(values) * self.config.anomaly_multiple,
        )

    @staticmethod
    def _depth(market: Any, ep: Episode) -> float | None:
        book = market.bids if ep.direction == "sell" else market.asks
        if not book or ep.depth_low is None or ep.depth_high is None:
            return None
        if min(book) > ep.depth_low or max(book) < ep.depth_high:
            return None  # The fixed price band has left the observable book.
        return float(sum(p * q for p, q in book.items() if ep.depth_low <= p <= ep.depth_high))

    def _evaluate(self, at: float, market: Any) -> None:
        self.last_eval = at
        self.valid_until = (
            min(market.book_at, market.book_exchange_at, self.last_trade_at) + self.config.max_age_s
            if self.last_trade_at is not None
            else None
        )
        windows = {str(n): self._window(at, n) for n in (5, 30, 120)}
        short, recent = windows["5"], windows["30"]
        thresholds = {"sell": self._threshold(0), "buy": self._threshold(1)}
        self.metrics = {
            "windows": windows,
            "threshold_usd_estimate": thresholds,
            "oi_context": {
                "value": market.ticker.get("openInterest"),
                "ticker_received_at": getattr(market, "ticker_at", None),
                "used_in_classification": False,
            },
            "baseline_windows": len(self.baseline),
        }
        ready = (
            self.started is not None
            and at - self.started >= self.config.warmup_s
            and len(self.baseline) >= self.config.min_baseline_windows
        )
        self.quality = "ready" if ready else "warming"
        self.reason = "observed_feed_only" if ready else "collecting_baseline"
        fresh_trades = (
            self.last_trade_at is not None and 0 <= at - self.last_trade_at <= self.config.max_age_s
        )
        if not fresh_trades and ready:
            self.quality, self.reason = "unavailable", "insufficient_recent_trades"
        if ready:
            for direction in ("sell", "buy"):
                self._direction(direction, at, market, short, recent, thresholds[direction])
        # Non-overlapping receipt windows. Current window cannot set its own threshold.
        slot = int(at // 30)
        if self.baseline_slot is None:
            self.baseline_slot = slot
        elif slot != self.baseline_slot:
            if (
                slot == self.baseline_slot + 1
                and self.started is not None
                and self.started <= self.baseline_slot * 30
                and not self.episodes
            ):
                self.baseline.append(
                    (
                        sum(
                            b.long_liquidations
                            for b in self.buckets
                            if self.baseline_slot * 30 <= b.at < slot * 30
                        ),
                        sum(
                            b.short_liquidations
                            for b in self.buckets
                            if self.baseline_slot * 30 <= b.at < slot * 30
                        ),
                    )
                )
            self.baseline_slot = slot

    def _direction(
        self,
        direction: str,
        at: float,
        market: Any,
        short: dict[str, float],
        recent: dict[str, float],
        threshold: float,
    ) -> None:
        sell = direction == "sell"
        liq_key = "long_liquidation_usd_estimate" if sell else "short_liquidation_usd_estimate"
        flow_key, opposite = ("sell_usd", "buy_usd") if sell else ("buy_usd", "sell_usd")
        sign = -1 if sell else 1
        movement = sign * (recent["last"] / recent["first"] - 1) * 10000 if recent["first"] else 0
        flow = recent[flow_key]
        wave = (
            recent[liq_key] >= threshold
            and flow >= self.config.minimum_traded_usd
            and flow > recent[opposite]
            and movement >= self.config.movement_bps
        )
        ep = self.episodes.get(direction)
        extreme = recent["low"] if sell else recent["high"]
        if ep is None:
            if not wave:
                return
            ident = f"{self.symbol}:{self.generation}:{direction}:{at:.6f}"
            ep = Episode(ident, direction, at, "pressure", extreme, recent[liq_key], at)
            self.episodes[direction] = ep
            return
        ep.peak = max(ep.peak, recent[liq_key])
        new_extreme = short["low"] < ep.extreme if sell else short["high"] > ep.extreme
        new_extreme = bool(short["trades"] and new_extreme)
        if new_extreme:
            ep.extreme = short["low"] if sell else short["high"]
        if wave or (new_extreme and short[flow_key] > short[opposite]):
            ep.state, ep.reason = "pressure", "new_wave_or_continued_aggression"
            ep.last_wave = at
            ep.checking_since = ep.anchor = ep.normal_since = None
            return
        active_trades = (
            short["trades"] >= 2
            and short["buy_usd"] + short["sell_usd"] >= self.config.minimum_traded_usd
        )
        calm = (
            recent[liq_key] < threshold * 0.25
            and recent["trades"] >= 2
            and recent[flow_key] <= recent[opposite]
            and not new_extreme
        )
        if calm and active_trades:
            ep.normal_since = ep.normal_since or at
            if at - ep.normal_since >= self.config.normalization_s:
                self.history.append({**asdict(ep), "ended": at, "outcome": "normalized"})
                del self.episodes[direction]
                return
        else:
            ep.normal_since = None
        if ep.state == "recovery":
            depth = self._depth(market, ep)
            if depth is None:
                ep.state, ep.reason = "mixed", "recovery_band_unobservable"
            elif ep.depth_reference is not None and depth < ep.depth_reference:
                ep.state, ep.reason = "mixed", "recovery_depth_lost"
                ep.checking_since = ep.anchor = None
            elif new_extreme:
                ep.state, ep.reason = "mixed", "recovery_level_lost"
            return
        if at - ep.started >= self.config.deadline_s:
            ep.state, ep.reason = "mixed", "confirmation_deadline"
            return
        if recent[liq_key] >= ep.peak * 0.5 or not active_trades:
            ep.state, ep.reason = "mixed", "insufficient_new_evidence"
            ep.checking_since = ep.anchor = None
            return
        if ep.checking_since is None:
            book = market.bids if sell else market.asks
            if len(book) < 10:
                ep.state, ep.reason = "mixed", "insufficient_depth_levels"
                return
            ep.state, ep.reason = "easing", "waiting_independent_flow"
            ep.checking_since, ep.anchor = at, ep.extreme
            levels = sorted(book, reverse=sell)[:10]
            ep.depth_low, ep.depth_high = min(levels), max(levels)
            ep.depth_reference = self._depth(market, ep)
            return
        after = [b for b in self.buckets if b.at > ep.checking_since]
        load = sum(b.sells if sell else b.buys for b in after)
        prices = [b.low if sell else b.high for b in after if b.trades]
        held = bool(
            prices
            and ep.anchor is not None
            and (min(prices) >= ep.anchor if sell else max(prices) <= ep.anchor)
        )
        depth = self._depth(market, ep)
        if depth is None or ep.depth_reference is None or depth < ep.depth_reference:
            ep.state, ep.reason = "mixed", "confirmation_depth_lost"
            ep.checking_since = ep.anchor = None
        elif prices and not held:
            ep.state, ep.reason = "mixed", "confirmation_level_lost"
            ep.checking_since = ep.anchor = None
        elif (
            at - ep.checking_since >= self.config.confirmation_s
            and load >= self.config.minimum_traded_usd
            and depth is not None
            and ep.depth_reference is not None
            and depth >= ep.depth_reference
        ):
            ep.state, ep.reason = "recovery", "new_flow_absorbed_in_observed_band"
        else:
            ep.reason = "waiting_flow_and_observable_depth"

    def snapshot(self, at: float | None = None) -> dict[str, Any]:
        now = self.last_receipt if at is None else at
        quality, reason = self.quality, self.reason
        if (
            self.enabled
            and now is not None
            and quality == "ready"
            and (
                now < self.last_eval
                or now - self.last_eval > self.config.max_age_s
                or self.valid_until is None
                or now > self.valid_until
            )
        ):
            quality, reason = "unavailable", "observer_stale"
        blocked = [
            "Buy" if k == "sell" else "Sell"
            for k, ep in self.episodes.items()
            if ep.state != "recovery"
        ]
        if quality not in {"ready", "off"}:
            blocked = ["Buy", "Sell"]
        return {
            "mode": "observe" if self.enabled else "off",
            "version": self.version,
            "symbol": self.symbol,
            "at": self.last_receipt,
            "evaluated_at": self.last_eval if math.isfinite(self.last_eval) else None,
            "valid_until": self.valid_until,
            "quality": quality,
            "reason": reason,
            "error": self.error,
            "generation": self.generation,
            "affects_orders": False,
            "max_age_s": self.config.max_age_s,
            "would_block": sorted(blocked),
            "metrics": deepcopy(self.metrics),
            "episodes": [asdict(e) for e in self.episodes.values()],
            "recent_episodes": deepcopy(list(self.history)),
        }

    def _record(self, at: float, force: bool = False) -> dict[str, Any] | None:
        signature = json.dumps(
            [
                self.quality,
                self.reason,
                self.error,
                [(e.id, e.state, e.reason) for e in self.episodes.values()],
                len(self.history),
            ],
            sort_keys=True,
        )
        if force or signature != self.signature or at - self.last_journal >= self.config.journal_s:
            self.signature, self.last_journal = signature, at
            self.last_record = self.snapshot()
            return self.last_record
        return None
