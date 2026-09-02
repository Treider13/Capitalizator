"""Live public recorder on pybit's WebSocket (D-44). Streams, does not buffer an hour.

Before: no socket existed in the repo (`opener` had to be injected), `recv_ts`
was stamped once per run, frames were collected into a list before any write,
and the sink rewrote the hourly file on every event.

Now:
  * pybit `WebSocket(channel_type="linear")` with ping 20s and auto-restart
    (https://bybit-exchange.github.io/docs/v5/ws/connect: ping every 20s);
  * `publicTrade.<sym>`, `orderbook.50.<sym>`, `tickers.<sym>` for the desk
    universe. Bybit docs (ws/connect, "Public channel - Args limits"): one
    connection's args may not exceed 21 000 characters; spot takes ≤10 args per
    request, futures "no args limit for now". pybit sends one request per call
    and does NOT batch, and `args size >10` rejections are reported in the wild
    (tiagosiebler/bybit-api#174), so we subscribe in chunks of 10 ourselves;
  * every frame gets its own `recv_ts` on arrival (callback thread), then is
    parked in a queue; the main thread normalises with the existing
    TradesNormalizer / BybitBookWs (gap → REST snapshot via RestSnapshot) /
    ticker_events and writes through `BufferedParquetSink` (immutable parts);
  * a status JSON (frames, last age per stream, gaps, dropped) is written for
    the console every second — an honest "recorder silent for N s" banner.
"""

from __future__ import annotations

import json
import queue
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.book.reconstruct import BookDirty
from capitalizator.ops.knowledge import Knowledge
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.live import ticker_events
from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.recorder.public_ws import is_control_frame
from capitalizator.recorder.rest_snapshot import BookSnapshot, RestSnapshot
from capitalizator.recorder.sink_parquet import BufferedParquetSink
from capitalizator.recorder.ws_book import BybitBookWs
from capitalizator.types import MarketEvent

Frame = Mapping[str, Any]
WsFactory = Callable[[], Any]
BOOK_DEPTH = 50  # docs: linear orderbook depth ∈ {1, 50, 200, 1000}
SUBSCRIBE_CHUNK = 10  # docs: spot ≤10 args/request; observed `args size >10` rejections


def make_public_ws(*, testnet: bool = False) -> Any:
    from pybit.unified_trading import WebSocket

    return WebSocket(
        testnet=testnet,
        channel_type="linear",
        ping_interval=20,
        ping_timeout=10,
        retries=200,
        restart_on_error=True,
    )


@dataclass
class StreamStat:
    frames: int = 0
    events: int = 0
    last_at: datetime | None = None
    errors: int = 0
    gaps: int = 0


@dataclass
class LiveRecorder:
    symbols: Sequence[str]
    data_root: Path
    ws_factory: WsFactory = make_public_ws
    knowledge: Knowledge | None = None
    fetch_snapshot: Callable[[str], BookSnapshot] | None = None
    sink: BufferedParquetSink | None = None
    q: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=200_000))
    stats: dict[str, StreamStat] = field(default_factory=dict)
    dropped: int = 0
    books: dict[str, BybitBookWs] = field(default_factory=dict)
    trades: TradesNormalizer = field(default_factory=TradesNormalizer)
    ws: Any = None
    started_at: datetime | None = None
    _last_status: float | None = None

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("symbols required")
        if self.sink is None:
            self.sink = BufferedParquetSink(self.data_root, flush_every_s=1.0, max_rows=5000)
        if self.fetch_snapshot is None:
            rest = RestSnapshot()
            self.fetch_snapshot = rest.fetch
        for name in ("trades", "book", "ticker"):
            self.stats[name] = StreamStat()

    # --- socket side (pybit thread) ----------------------------------------------------
    def start(self) -> None:
        self.started_at = datetime.now(tz=UTC)
        self.ws = self.ws_factory()
        syms = list(self.symbols)
        for chunk in (syms[i : i + SUBSCRIBE_CHUNK] for i in range(0, len(syms), SUBSCRIBE_CHUNK)):
            self.ws.trade_stream(chunk, self._cb("trades"))
            self.ws.orderbook_stream(BOOK_DEPTH, chunk, self._cb("book"))
            self.ws.ticker_stream(chunk, self._cb("ticker"))

    def _cb(self, stream: str) -> Callable[[Frame], None]:
        def handle(frame: Frame) -> None:
            # recv_ts per frame, on arrival (Н-2). Nothing else on this thread.
            try:
                self.q.put_nowait((stream, datetime.now(tz=UTC), frame))
            except queue.Full:
                self.dropped += 1

        return handle

    # --- main thread ---------------------------------------------------------------------
    def drain(self, *, max_frames: int = 20_000) -> int:
        n = 0
        while n < max_frames:
            try:
                stream, recv_ts, frame = self.q.get_nowait()
            except queue.Empty:
                break
            self.handle(stream, frame, recv_ts=recv_ts)
            n += 1
        assert self.sink is not None
        self.sink.maybe_flush(time.monotonic())
        return n

    def handle(self, stream: str, frame: Frame, *, recv_ts: datetime) -> list[MarketEvent]:
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
                        fetch_snapshot=(lambda s=symbol: fetch(s)) if fetch else None,
                    )
                    self.books[symbol] = worker
                events = worker.ingest_frames([frame], recv_ts=recv_ts)
                if any(e.stream in {"gap", "resync"} for e in events):
                    stat.gaps += 1
            elif stream == "ticker":
                events = ticker_events(frame, recv_ts=recv_ts)
        except (ValueError, BookDirty, SeqFault, KeyError):
            stat.errors += 1
            return []
        assert self.sink is not None
        for event in events:
            self.sink.write(event)
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

    def publish_status(self, *, now: datetime | None = None, every_s: float = 1.0) -> bool:
        if self.knowledge is None or not self.knowledge.available():
            return False
        mono = time.monotonic()
        if self._last_status is not None and mono - self._last_status < every_s:
            return False
        self._last_status = mono
        self.knowledge.set_meta("recorder_status", json.dumps(self.status(now), default=str))
        return True

    def run(
        self,
        *,
        should_stop: Callable[[], bool],
        idle_s: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.start()
        try:
            while not should_stop():
                n = self.drain()
                self.publish_status()
                if n == 0 and idle_s:
                    sleep(idle_s)
        finally:
            assert self.sink is not None
            self.sink.flush()
            self.publish_status(every_s=0)
            ws = self.ws
            if ws is not None and hasattr(ws, "exit"):
                try:
                    ws.exit()
                except Exception:
                    pass
