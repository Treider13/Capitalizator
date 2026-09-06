"""Live public recorder on a raw Bybit v5 socket (D-44). Streams, does not buffer an hour.

Why raw and not pybit's `WebSocket` (audit B2, verified on pybit 5.17): pybit
rebuilds the book locally and hands every callback `type="snapshot"` with the full
book; the deltas the desk needs for the 8 s ZLG/ОКО window never arrive. Same for
`tickers`. `recorder/raw_ws.py` passes frames through untouched.

  * `publicTrade.<sym>`, `orderbook.<depth>.<sym>`, `tickers.<sym>`,
    `allLiquidation.<sym>` for the desk universe (docs/v5/websocket/public/*);
    subscribed in chunks of ≤10 args, re-subscribed after a reconnect;
  * every frame gets its own `recv_ts` on arrival (socket thread), then is
    parked in a per-stream queue (book cannot fill the cap and drop trades);
    the main thread drains trades first, then book, and normalises with
    TradesNormalizer / BybitBookWs (gap → REST snapshot via RestSnapshot) /
    ticker_events / liquidation_events and writes through `BufferedParquetSink`
    (immutable parts);
  * a status JSON (frames, last age per stream, gaps, dropped, socket state) is
    written for the console every second — an honest "recorder silent for N s".
"""

from __future__ import annotations

import json
import queue
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from capitalizator.book.reconstruct import BookDirty
from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.wake import desk_wake_from_tape
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.live import liquidation_events, ticker_events
from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.recorder.public_ws import is_control_frame
from capitalizator.recorder.raw_ws import RawPublicWs
from capitalizator.recorder.rest_snapshot import BookSnapshot, RestSnapshot
from capitalizator.recorder.rest_ticker import RestTicker
from capitalizator.recorder.sink_parquet import BufferedParquetSink
from capitalizator.recorder.ws_book import BybitBookWs
from capitalizator.types import MarketEvent

Frame = Mapping[str, Any]
WsFactory = Callable[[], Any]
BOOK_DEPTH = 200  # docs: linear orderbook depth ∈ {1, 50, 200, 500, 1000}; 200 = deltas + depth
SUBSCRIBE_CHUNK = 10  # docs: spot ≤10 args/request; observed `args size >10` rejections


def make_public_ws(*, testnet: bool = False) -> Any:
    """Raw socket: deltas untouched. `start()` is called by LiveRecorder.start."""
    return RawPublicWs(testnet=testnet)


@dataclass
class StreamStat:
    frames: int = 0
    events: int = 0
    last_at: datetime | None = None
    errors: int = 0
    gaps: int = 0


STREAMS = ("trades", "book", "ticker", "liquidation")
# orderbook.200 is the firehose. One shared park lets book fill the cap and
# publicTrade never lands — same starve TapeCursor already split: origin jsonl
# has its own budget, trades do not share it. Official Bybit is still one
# socket / many topics; parking is per stream. Drain trades first, then book.
_STREAM_QSIZE = {"trades": 50_000, "book": 100_000, "ticker": 25_000, "liquidation": 25_000}


class _QueueSizes:
    """`rec.q.qsize()` stays the sum so existing status/tests keep working."""

    def __init__(self, queues: Mapping[str, queue.Queue[Any]]) -> None:
        self._queues = queues

    def qsize(self) -> int:
        return sum(item.qsize() for item in self._queues.values())


@dataclass
class LiveRecorder:
    symbols: Sequence[str]
    data_root: Path
    ws_factory: WsFactory = make_public_ws
    knowledge: Knowledge | None = None
    fetch_snapshot: Callable[[str], BookSnapshot] | None = None
    sink: BufferedParquetSink | None = None
    q: Any = field(init=False)
    _qs: dict[str, queue.Queue[Any]] = field(init=False, repr=False)
    stats: dict[str, StreamStat] = field(default_factory=dict)
    dropped: int = 0
    books: dict[str, BybitBookWs] = field(default_factory=dict)
    trades: TradesNormalizer = field(default_factory=TradesNormalizer)
    ws: Any = None
    started_at: datetime | None = None
    _last_status: float | None = None
    # last trade time per symbol (this process) and the reconnect count we last marked
    last_trade_ts: dict[str, datetime] = field(default_factory=dict)
    _marked_reconnects: int = 0
    _last_instruments: float | None = None
    rest_ticker: RestTicker | None = None
    rest_opener: Callable[[str], Any] | None = None
    rest_fallback: bool = False

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("symbols required")
        if self.sink is None:
            # Live feed (jsonl, per event) for the desk; parquet archive parts once a
            # minute (compacted later). 1 s parts × 10 symbols × 4 streams — the old
            # files/min on the VPS (2026-09-03) — the desk's own cursor choked on them.
            self.sink = BufferedParquetSink(
                self.data_root,
                flush_every_s=60.0,
                max_rows=200_000,
                live_jsonl=True,
                on_write=desk_wake_from_tape(self.data_root).notify,
            )
        if self.fetch_snapshot is None:
            rest = RestSnapshot()
            self.fetch_snapshot = rest.fetch
        if self.rest_ticker is None:
            self.rest_ticker = RestTicker()
        self._qs = {
            name: queue.Queue(maxsize=_STREAM_QSIZE[name]) for name in STREAMS
        }
        self.q = _QueueSizes(self._qs)
        for name in STREAMS:
            self.stats[name] = StreamStat()

    # --- socket side (pybit thread) ----------------------------------------------------
    def start(self) -> None:
        self.started_at = datetime.now(tz=UTC)
        self.ws = self.ws_factory()
        self._subscribe(list(self.symbols))
        if hasattr(self.ws, "start"):
            self.ws.start()

    def _subscribe(self, symbols: Sequence[str]) -> None:
        if self.ws is None or not symbols:
            return
        syms = list(symbols)
        for chunk in (syms[i : i + SUBSCRIBE_CHUNK] for i in range(0, len(syms), SUBSCRIBE_CHUNK)):
            self.ws.trade_stream(chunk, self._cb("trades"))
            self.ws.orderbook_stream(BOOK_DEPTH, chunk, self._cb("book"))
            self.ws.ticker_stream(chunk, self._cb("ticker"))
            if hasattr(self.ws, "liquidation_stream"):
                self.ws.liquidation_stream(chunk, self._cb("liquidation"))

    def _topics_for(self, symbols: Sequence[str]) -> list[str]:
        out: list[str] = []
        for symbol in symbols:
            out.extend(
                (
                    f"publicTrade.{symbol}",
                    f"orderbook.{BOOK_DEPTH}.{symbol}",
                    f"tickers.{symbol}",
                    f"allLiquidation.{symbol}",
                )
            )
        return out

    def set_symbols(self, symbols: Sequence[str]) -> dict[str, tuple[str, ...]]:
        """Hot universe change: subscribe added names, drop removed ones. No restart."""
        wanted = tuple(str(s) for s in symbols)
        if not wanted:
            raise ValueError("symbols required")
        old = tuple(self.symbols)
        if wanted == old:
            return {"added": (), "dropped": ()}
        added = tuple(s for s in wanted if s not in set(old))
        dropped = tuple(s for s in old if s not in set(wanted))
        self.symbols = wanted
        if self.ws is not None:
            if added:
                self._subscribe(added)
            if dropped and hasattr(self.ws, "drop_topics"):
                self.ws.drop_topics(self._topics_for(dropped))
            for symbol in dropped:
                self.books.pop(symbol, None)
        return {"added": added, "dropped": dropped}

    def _cb(self, stream: str) -> Callable[[Frame], None]:
        parked = self._qs[stream]

        def handle(frame: Frame) -> None:
            # recv_ts per frame, on arrival (Н-2). Nothing else on this thread.
            # A full book queue drops book frames only — trades still park.
            try:
                parked.put_nowait((datetime.now(tz=UTC), frame))
            except queue.Full:
                self.dropped += 1

        return handle

    # --- main thread ---------------------------------------------------------------------
    def drain(self, *, max_frames: int = 20_000) -> int:
        n = 0
        for name in STREAMS:
            while n < max_frames:
                try:
                    recv_ts, frame = self._qs[name].get_nowait()
                except queue.Empty:
                    break
                self.handle(name, frame, recv_ts=recv_ts)
                n += 1
        assert self.sink is not None
        self.sink.maybe_flush(time.monotonic())
        if self.rest_fallback:
            self.poll_rest_tickers(now=datetime.now(tz=UTC))
        return n

    def poll_rest_tickers(self, *, now: datetime) -> int:
        """REST funding/OI/mark when the public ticker socket is quiet."""
        if self.rest_ticker is None or self.sink is None:
            return 0
        ticker = self.stats.get("ticker")
        if ticker is not None and ticker.last_at is not None:
            if (now - ticker.last_at).total_seconds() < 60:
                return 0
        written = 0
        for symbol in self.symbols:
            try:
                events = self.rest_ticker.fetch(
                    symbol, recv_ts=now, opener=self.rest_opener
                )
            except (ValueError, OSError, json.JSONDecodeError):
                continue
            for event in events:
                self.sink.write(event)
                written += 1
        if written and ticker is not None:
            ticker.last_at = now
            ticker.events += written
        return written

    def handle(self, stream: str, frame: Frame, *, recv_ts: datetime) -> list[MarketEvent]:
        frame = dict(frame)
        stat = self.stats[stream]
        stat.frames += 1
        stat.last_at = recv_ts
        if is_control_frame(frame):
            return []
        events: list[MarketEvent] = []
        try:
            if stream == "trades":
                events = self.trades.normalize_frame(frame, recv_ts=recv_ts)
            elif stream == "book":
                topic = str(frame.get("topic") or "")
                symbol = topic.rsplit(".", 1)[-1] if "." in topic else str(self.symbols[0])
                worker = self.books.get(symbol)
                if worker is None:
                    fetch = self.fetch_snapshot
                    worker = BybitBookWs(
                        symbol=symbol,
                        fetch_snapshot=partial(fetch, symbol) if fetch else None,
                    )
                    self.books[symbol] = worker
                events = worker.ingest_frames([frame], recv_ts=recv_ts)
                if any(e.stream in {"gap", "resync"} for e in events):
                    stat.gaps += 1
            elif stream == "ticker":
                events = ticker_events(frame, recv_ts=recv_ts)
            elif stream == "liquidation":
                events = liquidation_events(frame, recv_ts=recv_ts)
        except (ValueError, BookDirty, SeqFault, KeyError):
            stat.errors += 1
            return []
        assert self.sink is not None
        for event in events:
            self.sink.write(event)
            if event.stream == "trades":
                self.last_trade_ts[event.symbol] = event.exchange_ts
        stat.events += len(events)
        return events

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        when = now or datetime.now(tz=UTC)
        assert self.sink is not None
        out: dict[str, Any] = {
            "at": when.isoformat(),
            "symbols": list(self.symbols),
            "dropped": self.dropped,
            "pending_rows": self.sink.pending(),
            "flushed_rows": self.sink.flushed_count,
            "parts_written": self.sink.parts_written,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "socket_connected": self._socket_connected(),
            "reconnects": getattr(self.ws, "reconnects", None),
            "last_trade_ts": {k: v.isoformat() for k, v in sorted(self.last_trade_ts.items())},
            "streams": {},
        }
        for name, st in self.stats.items():
            age = None if st.last_at is None else (when - st.last_at).total_seconds()
            out["streams"][name] = {
                "frames": st.frames,
                "events": st.events,
                "errors": st.errors,
                "gaps": st.gaps,
                "last_age_s": age,
            }
        return out

    def mark_time_gap(self, *, now: datetime, reason: str) -> int:
        """Write one `gap` event per symbol with ts_from/ts_to: the hole this process
        knows about (F0 law: a restart or a reconnect is a MARKED hole; an unmarked one
        is a silent death). ts_from = the last trade we saw for the symbol — in this
        process, or, at startup, in the previous process's `recorder_status`."""
        assert self.sink is not None
        n = 0
        for symbol in self.symbols:
            since = self.last_trade_ts.get(symbol)
            if since is None:
                since = self._previous_last_trade(symbol)
            if since is None or since >= now:
                continue
            self.sink.write(
                MarketEvent(
                    stream="gap",
                    exchange="bybit",
                    symbol=symbol,
                    exchange_ts=since,
                    recv_ts=now,
                    seq=None,
                    payload={
                        "ts_from": since.isoformat(),
                        "ts_to": now.isoformat(),
                        "reason": reason,
                    },
                )
            )
            n += 1
        return n

    def _previous_last_trade(self, symbol: str) -> datetime | None:
        if self.knowledge is None or not self.knowledge.available():
            return None
        raw = self.knowledge.meta("recorder_status")
        if not raw:
            return None
        try:
            prev = json.loads(raw)
            stamp = (prev.get("last_trade_ts") or {}).get(symbol)
            return None if not stamp else datetime.fromisoformat(str(stamp))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            return None

    def mark_reconnects(self, *, now: datetime | None = None) -> int:
        """Called from the main loop: every reconnect the socket counted since the last
        call becomes a marked hole (ts_from = last trade before it)."""
        count = getattr(self.ws, "reconnects", None)
        if not isinstance(count, int) or count <= self._marked_reconnects:
            return 0
        self._marked_reconnects = count
        return self.mark_time_gap(now=now or datetime.now(tz=UTC), reason="reconnect")

    def _socket_connected(self) -> bool | None:
        ws = self.ws
        if ws is None or not hasattr(ws, "is_connected"):
            return None
        return bool(ws.is_connected())

    def publish_status(self, *, now: datetime | None = None, every_s: float = 1.0) -> bool:
        if self.knowledge is None or not self.knowledge.available():
            return False
        mono = time.monotonic()
        if self._last_status is not None and mono - self._last_status < every_s:
            return False
        self._last_status = mono
        self.knowledge.set_meta("recorder_status", json.dumps(self.status(now), default=str))
        return True

    INSTRUMENTS_EVERY_S = 3600.0

    def publish_instruments(self, *, testnet: bool = False, force: bool = False) -> int | None:
        """Public instruments-info → knowledge, hourly. Errors are recorded, not raised."""
        if self.knowledge is None or not self.knowledge.available():
            return None
        mono = time.monotonic()
        if not force and self._last_instruments is not None:
            if mono - self._last_instruments < self.INSTRUMENTS_EVERY_S:
                return None
        self._last_instruments = mono
        from capitalizator.recorder.public_rest import publish_instruments

        try:
            n = publish_instruments(self.knowledge, testnet=testnet)
        except Exception as exc:  # network / venue: say why (type + code), keep recording
            code = getattr(exc, "code", None)
            self.knowledge.set_meta(
                "instruments_error_recorder", type(exc).__name__ + (f" {code}" if code else "")
            )
            return None
        self.knowledge.set_meta("instruments_error_recorder", "")
        return n

    def run(
        self,
        *,
        should_stop: Callable[[], bool],
        idle_s: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
        testnet: bool = False,
        universe_fn: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        # the hole between the previous process's last trade and now is OURS to mark
        self.mark_time_gap(now=datetime.now(tz=UTC), reason="start")
        self.start()
        self.publish_instruments(testnet=testnet, force=True)
        try:
            while not should_stop():
                if universe_fn is not None:
                    self.set_symbols(universe_fn())
                n = self.drain()
                self.mark_reconnects()
                self.publish_status()
                self.publish_instruments(testnet=testnet)
                if n == 0 and idle_s:
                    sleep(idle_s)
        finally:
            assert self.sink is not None
            self.sink.flush()
            self.sink.close()
            self.publish_status(every_s=0)
            ws = self.ws
            if ws is not None and hasattr(ws, "exit"):
                try:
                    ws.exit()
                except Exception:
                    pass
