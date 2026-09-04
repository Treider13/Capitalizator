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
from capitalizator.recorder.ticker_fields import funding_payload
from capitalizator.recorder.ws_book import BybitBookWs
from capitalizator.types import MarketEvent, require_utc

Opener = Callable[[str, str, int], Iterable[dict[str, Any]]]
LIVE_STREAMS = ("trades", "book", "funding", "oi", "liquidation")


def liquidation_events(frame: dict[str, Any], *, recv_ts: datetime) -> list[MarketEvent]:
    """allLiquidation.{symbol}: data is a list of {T, s, S, v, p}.

    Official: S is the *position* side — `Buy` means a long was liquidated.
    We keep that as payload.position = long|short and do not re-label it as a taker.
    p is the bankruptcy price. A row without T/s/S/v/p is an error, not a zero.
    """
    if is_control_frame(frame):
        return []
    data = frame.get("data")
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = [row for row in data if isinstance(row, dict)]
    else:
        return []
    when = require_utc(recv_ts)
    out: list[MarketEvent] = []
    for row in rows:
        missing = [k for k in ("T", "s", "S", "v", "p") if k not in row]
        if missing:
            raise ValueError(f"liquidation row missing {missing}")
        side = str(row["S"]).lower()
        if side not in {"buy", "sell"}:
            raise ValueError(f"unknown liquidation side: {row['S']!r}")
        qty = str(row["v"])
        px = str(row["p"])
        if float(qty) <= 0 or float(px) <= 0:
            raise ValueError("liquidation v/p must be > 0")
        out.append(
            MarketEvent(
                stream="liquidation",
                exchange="bybit",
                symbol=str(row["s"]),
                exchange_ts=datetime.fromtimestamp(int(row["T"]) / 1000, tz=UTC),
                recv_ts=when,
                payload={
                    "px": px,
                    "qty": qty,
                    "position": "long" if side == "buy" else "short",
                },
            )
        )
    return out


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
                    payload=funding_payload(item),
                )
            )
        # `openInterest` is contracts; `openInterestValue` is USD — a ticker DELTA frame
        # may carry only the value, and mixing the two put 4.3e9 next to 55e3 in the OI
        # history (live, 2026-09-03). Only the contract figure is the OI series; the
        # value rides along as an extra field.
        if item.get("openInterest") is not None:
            payload: dict[str, str] = {"oi": str(item["openInterest"])}
            if item.get("openInterestValue") is not None:
                payload["oi_value"] = str(item["openInterestValue"])
            out.append(
                MarketEvent(
                    stream="oi",
                    exchange="bybit",
                    symbol=symbol,
                    exchange_ts=exchange_ts,
                    recv_ts=when,
                    payload=payload,
                )
            )
        mark_px = item.get("markPrice") or item.get("mark_price")
        if mark_px is not None:
            out.append(
                MarketEvent(
                    stream="mark",
                    exchange="bybit",
                    symbol=symbol,
                    exchange_ts=exchange_ts,
                    recv_ts=when,
                    payload={"mark": str(mark_px)},
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
    fetch_ticker: Callable[[], list[MarketEvent]] | None = None,
) -> int:
    if minutes <= 0:
        raise ValueError("minutes must be > 0")
    app.recording = True
    accepted = 0
    from capitalizator.ops.wake import desk_wake_from_tape

    sink = ParquetSink(data_root, on_write=desk_wake_from_tape(data_root).notify)
    names = list(symbols) if symbols else [symbol]
    wanted = list(streams) if streams else [stream]

    if events is not None:
        for event in events:
            sink.write(event)
            accepted += 1
            app.accepted_count = accepted
        return accepted

    if fetch_ticker is not None:
        for event in fetch_ticker():
            sink.write(event)
            accepted += 1
            app.accepted_count = accepted

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
        if not batch and (stream == "liquidation" or topic.startswith("allLiquidation.")):
            batch = liquidation_events(frame, recv_ts=now)
        for event in batch:
            sink.write(event)
            accepted += 1
            app.accepted_count = accepted
    return accepted


def subscribe_desk(symbols: Sequence[str]) -> dict[str, Any]:
    return subscribe_many(list(symbols), list(LIVE_STREAMS))
