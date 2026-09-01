"""Live tape runner. --minutes without jsonl is allowed.

A socket is a VPS concern: inject `frames` or `opener`. No keys.
Funding / OI / mark frames are accepted as already-normalized MarketEvents.
Gap/resync uses the existing book path (BookDirty + optional fetch).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.recorder.app import RecorderApp
from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.recorder.public_ws import is_control_frame, subscribe_many
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.recorder.ws_book import BybitBookWs
from capitalizator.types import MarketEvent, require_utc

Opener = Callable[[str, str, int], Iterable[dict[str, Any]]]
LIVE_STREAMS = ("trades", "book", "funding", "oi")


def ticker_events(frame: dict[str, Any], *, recv_ts: datetime) -> list[MarketEvent]:
    """tickers.{symbol} carries funding + OI. One frame → two streams if both present."""
    if is_control_frame(frame):
        return []
    data = frame.get("data")
    if isinstance(data, list):
        items = [row for row in data if isinstance(row, dict)]
    elif isinstance(data, dict):
        items = [data]
    elif "symbol" in frame or "s" in frame:
        items = [frame]
    else:
        return []
    when = require_utc(recv_ts)
    out: list[MarketEvent] = []
    for item in items:
        symbol = str(item.get("symbol") or item.get("s") or "")
        if not symbol:
            continue
        ts_raw = item.get("ts") or item.get("T") or frame.get("ts")
        exchange_ts = (
            datetime.fromtimestamp(int(ts_raw) / 1000, tz=UTC)
            if ts_raw is not None
            else when
        )
        if item.get("fundingRate") is not None:
            out.append(
                MarketEvent(
                    stream="funding",
                    exchange="bybit",
                    symbol=symbol,
                    exchange_ts=exchange_ts,
                    recv_ts=when,
                    payload={"funding": str(item["fundingRate"])},
                )
            )
        if item.get("openInterest") is not None or item.get("openInterestValue") is not None:
            oi = item.get("openInterest", item.get("openInterestValue"))
            out.append(
                MarketEvent(
                    stream="oi",
                    exchange="bybit",
                    symbol=symbol,
                    exchange_ts=exchange_ts,
                    recv_ts=when,
                    payload={"oi": str(oi)},
                )
            )
    return out


def run_live(
    app: RecorderApp,
    *,
    minutes: int,
    symbol: str,
    data_root: Path,
    stream: str = "trades",
    symbols: Sequence[str] | None = None,
    streams: Sequence[str] | None = None,
    frames: Iterable[dict[str, Any]] | None = None,
    events: Iterable[MarketEvent] | None = None,
    opener: Opener | None = None,
    fetch_snapshot: Callable[[], Any] | None = None,
) -> int:
    if minutes <= 0:
        raise ValueError("minutes must be > 0")
    app.recording = True
    accepted = 0
    sink = ParquetSink(data_root)
    names = list(symbols) if symbols else [symbol]
    wanted = list(streams) if streams else [stream]

    if events is not None:
        for event in events:
            sink.write(event)
            accepted += 1
            app.accepted_count = accepted
        return accepted

    raw_frames: Iterable[dict[str, Any]]
    if frames is not None:
        raw_frames = frames
    elif opener is not None:
        collected: list[dict[str, Any]] = []
        for name in names:
            for item in wanted:
                collected.extend(list(opener(name, item, minutes)))
        raw_frames = collected
    else:
        raw_frames = ()

    trades = TradesNormalizer()
    books: dict[str, BybitBookWs] = {}
    now = datetime.now(tz=UTC)
    for frame in raw_frames:
        if is_control_frame(frame):
            continue
        topic = str(frame.get("topic") or "")
        batch: list[MarketEvent] = []
        if stream == "trades" or topic.startswith("publicTrade"):
            try:
                batch = trades.normalize_frame(frame, recv_ts=now)
            except ValueError:
                batch = []
        if not batch and (stream == "book" or topic.startswith("orderbook")):
            name = names[0]
            if "." in topic:
                name = topic.rsplit(".", 1)[-1]
            worker = books.get(name)
            if worker is None:
                worker = BybitBookWs(symbol=name, fetch_snapshot=fetch_snapshot)
                books[name] = worker
            batch = worker.ingest_frames([frame], recv_ts=now)
        if not batch and (
            stream in {"funding", "oi", "ticker"} or topic.startswith("tickers.")
        ):
            batch = ticker_events(frame, recv_ts=now)
        for event in batch:
            sink.write(event)
            accepted += 1
            app.accepted_count = accepted
    return accepted


def subscribe_desk(symbols: Sequence[str]) -> dict[str, Any]:
    return subscribe_many(list(symbols), list(LIVE_STREAMS))
