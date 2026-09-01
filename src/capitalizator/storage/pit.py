"""0.2.8 — SQL over recorded events. Slice cannot see the future.

known_at := recv_ts (when we learned the print).
query(sql, as_of) runs SQL only on rows with known_at <= as_of.
DuckDB external files are off — SQL cannot open another parquet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import duckdb

from capitalizator.types import MarketEvent, known_by, require_utc


class PitStore:
    def __init__(self, events: list[MarketEvent]) -> None:
        self._events = events

    def query(self, sql: str, *, as_of: datetime) -> list[dict[str, Any]]:
        as_of_u = require_utc(as_of)
        visible = [e for e in self._events if known_by(e.recv_ts, as_of_u)]
        rows = [
            {
                "stream": e.stream,
                "exchange": e.exchange,
                "symbol": e.symbol,
                "exchange_ts": e.exchange_ts,
                "recv_ts": e.recv_ts,
                "known_at": e.recv_ts,
                "seq": e.seq,
            }
            for e in visible
        ]
        con = duckdb.connect(":memory:")
        try:
            # Fail closed: if this SET is missing, SQL must not read disk.
            con.execute("SET enable_external_access=false")
            con.execute(
                """
                CREATE TABLE market_event (
                    stream VARCHAR,
                    exchange VARCHAR,
                    symbol VARCHAR,
                    exchange_ts TIMESTAMP,
                    recv_ts TIMESTAMP,
                    known_at TIMESTAMP,
                    seq BIGINT
                )
                """
            )
            if rows:
                con.executemany(
                    "INSERT INTO market_event VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r["stream"],
                            r["exchange"],
                            r["symbol"],
                            r["exchange_ts"].replace(tzinfo=None),
                            r["recv_ts"].replace(tzinfo=None),
                            r["known_at"].replace(tzinfo=None),
                            r["seq"],
                        )
                        for r in rows
                    ],
                )
            con.execute("CREATE VIEW market_event_pit AS SELECT * FROM market_event")
            result = con.execute(sql)
            columns = [d[0] for d in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        finally:
            con.close()
