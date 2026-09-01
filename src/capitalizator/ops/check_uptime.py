"""Check recorded trade coverage. Does not invent a 24h live run.

A hole is silence between consecutive trade `exchange_ts` larger than
`--max-unmarked-gap-s` with no `stream=gap` event overlapping that interval.
`--hours` is the minimum span we demand. 0.1.7 stays red until a real VPS day.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from capitalizator.types import MarketEvent, require_utc


def parse_event_row(row: dict[str, Any]) -> MarketEvent | None:
    """One parquet row. Junk JSON / stream / naive clock is not a fact — skip."""
    try:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            return None
        return MarketEvent(
            stream=row["stream"],
            exchange=row["exchange"],
            symbol=row["symbol"],
            exchange_ts=row["exchange_ts"],
            recv_ts=row["recv_ts"],
            seq=row["seq"],
            payload=payload,
        )
    except (TypeError, ValueError, json.JSONDecodeError, KeyError):
        return None


def load_events(root: Path, *, symbol: str) -> list[MarketEvent]:
    events: list[MarketEvent] = []
    for path in root.rglob("*.parquet"):
        if symbol not in path.parts:
            continue
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, ValueError):
            continue
        for row in table.to_pylist():
            if row.get("symbol") != symbol:
                continue
            event = parse_event_row(row)
            if event is not None:
                events.append(event)
    return events


def gap_covers(gaps: list[MarketEvent], start: datetime, end: datetime) -> bool:
    """A seq-gap event does not mark a time hole unless payload has ts_from/ts_to."""
    start_u = require_utc(start)
    end_u = require_utc(end)
    for gap in gaps:
        raw_from = gap.payload.get("ts_from")
        raw_to = gap.payload.get("ts_to")
        if raw_from is None or raw_to is None:
            continue
        try:
            lo = require_utc(datetime.fromisoformat(str(raw_from)))
            hi = require_utc(datetime.fromisoformat(str(raw_to)))
        except (TypeError, ValueError):
            # Naive or unparsable clocks are not a cover. Same as a seq-gap.
            continue
        if lo > hi:
            lo, hi = hi, lo
        if lo <= start_u and hi >= end_u:
            return True
    return False


def check_uptime(
    events: list[MarketEvent],
    *,
    hours: float,
    max_unmarked_gap_s: float,
    symbol: str | None = None,
) -> float:
    if hours <= 0:
        raise ValueError("hours must be > 0")
    if max_unmarked_gap_s < 0:
        raise ValueError("max_unmarked_gap_s must be >= 0")
    trades = [e for e in events if e.stream == "trades"]
    if symbol is not None:
        trades = [e for e in trades if e.symbol == symbol]
    trades = sorted(trades, key=lambda e: e.exchange_ts)
    if len(trades) < 2:
        raise SystemExit("need at least two trades to measure span")
    span_s = (trades[-1].exchange_ts - trades[0].exchange_ts).total_seconds()
    need = hours * 3600
    if span_s + 1e-9 < need:
        raise SystemExit(f"span {span_s}s < required {need}s")
    gaps = [e for e in events if e.stream == "gap"]
    if symbol is not None:
        # An ETH restart must not paint a BTC hole green.
        gaps = [e for e in gaps if e.symbol == symbol]
    prev = trades[0]
    for cur in trades[1:]:
        hole = (cur.exchange_ts - prev.exchange_ts).total_seconds()
        if hole > max_unmarked_gap_s and not gap_covers(gaps, prev.exchange_ts, cur.exchange_ts):
            raise SystemExit(
                f"unmarked gap {hole}s between {prev.exchange_ts.isoformat()} "
                f"and {cur.exchange_ts.isoformat()}"
            )
        prev = cur
    return span_s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Uptime check on recorded parquet")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--universe", default=None)
    parser.add_argument("--hours", type=float, required=True)
    parser.add_argument("--max-unmarked-gap-s", type=float, required=True)
    args = parser.parse_args(argv)
    if args.universe:
        from capitalizator.screener.universe import load_universe

        universe = load_universe(Path(args.universe))
        spans: list[float] = []
        for symbol in universe.symbols:
            events = load_events(Path(args.data_root), symbol=symbol)
            spans.append(
                check_uptime(
                    events,
                    hours=args.hours,
                    max_unmarked_gap_s=args.max_unmarked_gap_s,
                    symbol=symbol,
                )
            )
        print(min(spans) if spans else 0.0)
        return 0
    events = load_events(Path(args.data_root), symbol=args.symbol)
    span = check_uptime(
        events,
        hours=args.hours,
        max_unmarked_gap_s=args.max_unmarked_gap_s,
        symbol=args.symbol,
    )
    print(span)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
