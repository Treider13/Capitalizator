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
        worker: BybitTradesWs | BybitBookWs = BybitTradesWs()
    elif stream == "book":
        worker = BybitBookWs()
    else:
        raise ValueError(f"unknown pump stream {stream!r}; use trades or book")
    accepted = 0
    for frame in frames:
        when = recv_ts or datetime.now(tz=UTC)
        for event in worker.ingest_frames([frame], recv_ts=when):
            sink.write(event)
            app.accepted_count += 1
            accepted += 1
    if accepted:
        app.recording = True
    return accepted


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
