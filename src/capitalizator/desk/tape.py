"""Read recorded parquet into desk. Regular files only. No invented rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from capitalizator.desk.bars import closed_bars_from_trades
from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.vault import VaultError, iter_regular_files
from capitalizator.types import MarketEvent
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Zone

Seen = set[tuple[str, str, str, int | None]]


def _parse(row: dict) -> MarketEvent | None:
    try:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            return None
        ts = row["exchange_ts"]
        recv = row["recv_ts"]
        if not isinstance(ts, datetime) or not isinstance(recv, datetime):
            return None
        return MarketEvent(
            stream=row["stream"],
            exchange=row["exchange"],
            symbol=row["symbol"],
            exchange_ts=ts,
            recv_ts=recv,
            seq=row.get("seq"),
            payload=payload,
        )
    except (TypeError, ValueError, json.JSONDecodeError, KeyError):
        return None


def load_tape(tape: Path) -> list[MarketEvent]:
    if tape.is_symlink() or not tape.is_dir():
        return []
    events: list[MarketEvent] = []
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return []
    for path in paths:
        if path.suffix != ".parquet":
            continue
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, ValueError):
            continue
        for row in table.to_pylist():
            event = _parse(row)
            if event is not None:
                events.append(event)
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


def consume_tape(
    desk: DeskLoop,
    tape: Path,
    *,
    seen: Seen,
    extra_zones: tuple[Zone, ...] = (),
    now: datetime | None = None,
) -> int:
    """Feed unseen parquet events into the loop. Second pass does not replay."""
    fresh: list[MarketEvent] = []
    for event in load_tape(tape):
        key = (event.stream, event.symbol, event.exchange_ts.isoformat(), event.seq)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(event)
    desk.play(fresh, extra_zones=extra_zones, now=now)
    return len(fresh)


def zones_for_trade(
    desk: DeskLoop,
    event: MarketEvent,
    extra_zones: Sequence[Zone] = (),
) -> list[Zone]:
    """Prior-day / swing zones from already-closed working-TF bars, plus extras."""
    engine = ZoneEngine(tick_size=desk.tick_size, config=desk.config)
    tf = desk.config.working_tf
    st = desk.state_for(event.symbol)
    work = [b for b in st.bars if b.tf == tf]
    built = engine.build(event.symbol, event.exchange_ts, work)
    return list(extra_zones) + built


def close_due_bars(desk: DeskLoop, symbol: str, now: datetime) -> list[dict[str, Any]]:
    """Close working TF first, then H4 and D1. CAV is the 15m vote (§6.3/§6.5)."""
    tfs = (desk.config.working_tf, desk.config.htf, desk.config.htf_d1)
    st = desk.state_for(symbol)
    out: list[dict[str, Any]] = []
    for tf in tfs:
        already = {b.open_ts for b in st.bars if b.tf == tf}
        for bar in closed_bars_from_trades(st.trades, symbol=symbol, tf=tf, now=now, already=already):
            out.extend(desk.on_bar_close(bar))
    return out


def _close_due_bars(desk: DeskLoop, symbol: str, now: datetime) -> None:
    close_due_bars(desk, symbol, now)
