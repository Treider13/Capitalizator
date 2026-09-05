"""15m bars from trade prints. Only closed buckets. No invented OHLC.

`closed_bars_from_trades` rescans every print (fixtures / replay of a short tape).
`BarBuilder` is the live path: O(1) per print, one open bucket per TF, closes on
the clock. Both produce the same Bar for the same prints (see tests/desk/test_bars).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.types import MarketEvent, require_utc
from capitalizator.zones.model import Bar

# 1m/5m are feature buckets only. ZoneEngine working_tf stays 15m (KNOWN_TFS).
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def bucket_open(ts: datetime, *, minutes: int) -> datetime:
    when = ts.astimezone(UTC)
    total = when.hour * 60 + when.minute
    floored = (total // minutes) * minutes
    return when.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def closed_bars_from_trades(
    trades: Sequence[MarketEvent],
    *,
    symbol: str,
    tf: str,
    now: datetime,
    already: set[datetime],
) -> list[Bar]:
    minutes = TF_MINUTES.get(tf)
    if minutes is None:
        raise ValueError(f"unsupported working tf: {tf!r}")
    buckets: dict[datetime, list[MarketEvent]] = {}
    for trade in trades:
        if trade.symbol != symbol or trade.stream != "trades":
            continue
        try:
            px = Decimal(str(trade.payload["px"]))
            qty = Decimal(str(trade.payload.get("qty") or "0"))
        except (KeyError, ArithmeticError):
            continue
        if px <= 0 or qty < 0:
            continue
        start = bucket_open(trade.exchange_ts, minutes=minutes)
        buckets.setdefault(start, []).append(trade)
    out: list[Bar] = []
    for start, rows in sorted(buckets.items()):
        close_ts = start + timedelta(minutes=minutes)
        if close_ts > now or start in already:
            continue
        px = [Decimal(str(r.payload["px"])) for r in rows]
        vol = sum((Decimal(str(r.payload.get("qty") or "0")) for r in rows), Decimal("0"))
        out.append(
            Bar(
                symbol=symbol,
                tf=tf,
                open_ts=start,
                close_ts=close_ts,
                open=px[0],
                high=max(px),
                low=min(px),
                close=px[-1],
                volume=vol,
            )
        )
    return out


@dataclass
class _OpenBucket:
    open_ts: datetime
    close_ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    n: int = 0


@dataclass
class BarBuilder:
    """Incremental OHLCV per (symbol, tf). Prints only; a bucket without prints is no bar."""

    symbol: str
    tfs: tuple[str, ...]
    _open: dict[str, _OpenBucket] = field(default_factory=dict)
    _ready: dict[str, list[_OpenBucket]] = field(default_factory=dict)
    _last_closed: dict[str, datetime] = field(default_factory=dict)
    late_prints: int = 0

    def __post_init__(self) -> None:
        for tf in self.tfs:
            if tf not in TF_MINUTES:
                raise ValueError(f"unsupported tf: {tf!r}")

    def seed_closed(self, bars: Sequence[Bar]) -> None:
        """Remember already-closed bars so a replayed print cannot reopen them."""
        for bar in bars:
            if bar.symbol != self.symbol or bar.tf not in self.tfs:
                continue
            prev = self._last_closed.get(bar.tf)
            if prev is None or bar.close_ts > prev:
                self._last_closed[bar.tf] = bar.close_ts

    def on_trade(self, trade: MarketEvent) -> None:
        if trade.symbol != self.symbol or trade.stream != "trades":
            return
        try:
            px = Decimal(str(trade.payload["px"]))
            qty = Decimal(str(trade.payload.get("qty") or "0"))
        except (KeyError, ArithmeticError):
            return
        if px <= 0 or qty < 0:
            return
        ts = require_utc(trade.exchange_ts)
        for tf in self.tfs:
            minutes = TF_MINUTES[tf]
            start = bucket_open(ts, minutes=minutes)
            last = self._last_closed.get(tf)
            if last is not None and start < last:
                # Print older than a bar we already closed: never rewrite history.
                self.late_prints += 1
                continue
            bucket = self._open.get(tf)
            if bucket is None or bucket.open_ts != start:
                if bucket is not None and bucket.open_ts > start:
                    self.late_prints += 1
                    continue
                if bucket is not None:
                    # A print from the next bucket proves this one is over; park it
                    # until the clock (close_due) emits it. Nothing is dropped.
                    self._ready.setdefault(tf, []).append(bucket)
                bucket = _OpenBucket(
                    open_ts=start,
                    close_ts=start + timedelta(minutes=minutes),
                    open=px,
                    high=px,
                    low=px,
                    close=px,
                    volume=Decimal("0"),
                )
                self._open[tf] = bucket
            bucket.high = max(bucket.high, px)
            bucket.low = min(bucket.low, px)
            bucket.close = px
            bucket.volume += qty
            bucket.n += 1

    def close_due(self, now: datetime) -> list[Bar]:
        """Close every open bucket whose close_ts <= now. Working TF first."""
        when = require_utc(now)
        out: list[Bar] = []
        for tf in self.tfs:
            parked = self._ready.get(tf, [])
            keep: list[_OpenBucket] = []
            for bucket in parked:
                if bucket.close_ts <= when:
                    bar = self._bar(tf, bucket)
                    if bar is not None:
                        out.append(bar)
                else:
                    keep.append(bucket)
            if keep:
                self._ready[tf] = keep
            elif tf in self._ready:
                del self._ready[tf]
            bucket = self._open.get(tf)
            if bucket is None or bucket.close_ts > when:
                continue
            bar = self._bar(tf, bucket)
            if bar is not None:
                out.append(bar)
            del self._open[tf]
        return out

    def _bar(self, tf: str, bucket: _OpenBucket) -> Bar | None:
        prev = self._last_closed.get(tf)
        if prev is not None and bucket.open_ts < prev:
            # Seeded/closed elsewhere while this bucket was open: not a second bar.
            return None
        self._last_closed[tf] = bucket.close_ts
        return Bar(
            symbol=self.symbol,
            tf=tf,
            open_ts=bucket.open_ts,
            close_ts=bucket.close_ts,
            open=bucket.open,
            high=bucket.high,
            low=bucket.low,
            close=bucket.close,
            volume=bucket.volume,
        )

    def open_bucket(self, tf: str) -> Bar | None:
        """Unclosed bar for display only. Never fed to CAV."""
        bucket = self._open.get(tf)
        if bucket is None:
            return None
        return Bar(
            symbol=self.symbol,
            tf=tf,
            open_ts=bucket.open_ts,
            close_ts=bucket.close_ts,
            open=bucket.open,
            high=bucket.high,
            low=bucket.low,
            close=bucket.close,
            volume=bucket.volume,
        )
