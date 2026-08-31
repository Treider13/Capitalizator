"""Pump already-decoded frames into parquet. No keys. No live socket.

`--minutes` without `--from-jsonl` still refuses: a public WS hour is
step 0.1.4 on a VPS, not this binary inventing an hour.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.recorder.app import RecorderApp
from capitalizator.recorder.public_ws import is_control_frame
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.recorder.ws_book import BybitBookWs
from capitalizator.recorder.ws_trades import BybitTradesWs


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("jsonl line must be an object")
        out.append(raw)
    return out


def pump_frames(
    app: RecorderApp,
    sink: ParquetSink,
    frames: Iterable[dict[str, Any]],
    *,
    stream: str,
    recv_ts: datetime | None = None,
) -> int:
    if stream == "trades":
        trades = BybitTradesWs()
        return _write(app, sink, _trade_events(trades, frames, recv_ts=recv_ts))
    if stream == "book":
        book = BybitBookWs()
        return _write(app, sink, _book_events(book, frames, recv_ts=recv_ts))
    raise ValueError(f"unknown pump stream {stream!r}; use trades or book")


def _trade_events(
    worker: BybitTradesWs,
    frames: Iterable[dict[str, Any]],
    *,
    recv_ts: datetime | None,
) -> list[Any]:
    events: list[Any] = []
    for frame in frames:
        when = recv_ts or datetime.now(tz=UTC)
        events.extend(worker.run([frame], recv_ts=when))
    return events


def _book_events(
    worker: BybitBookWs,
    frames: Iterable[dict[str, Any]],
    *,
    recv_ts: datetime | None,
) -> list[Any]:
    events: list[Any] = []
    for frame in frames:
        if is_control_frame(frame):
            continue
        when = recv_ts or datetime.now(tz=UTC)
        events.extend(worker.ingest_frames([frame], recv_ts=when))
    return events


def _write(app: RecorderApp, sink: ParquetSink, events: list[Any]) -> int:
    for event in events:
        sink.write(event)
        app.accepted_count += 1
    if events:
        app.recording = True
    return len(events)


def pump_jsonl(
    app: RecorderApp,
    data_root: Path,
    jsonl_path: Path,
    *,
    stream: str,
    recv_ts: datetime | None = None,
) -> int:
    sink = ParquetSink(data_root)
    return pump_frames(app, sink, load_jsonl(jsonl_path), stream=stream, recv_ts=recv_ts)
