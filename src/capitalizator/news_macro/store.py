"""News table with PIT: a slice cannot see a row before known_at."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import duckdb

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.types import known_by, require_utc


class NewsStore:
    def __init__(self, rows: Sequence[NewsRow]) -> None:
        self._rows = list(rows)

    def query(self, sql: str, *, as_of: datetime) -> list[dict[str, Any]]:
        as_of_u = require_utc(as_of)
        visible = [r for r in self._rows if known_by(r.known_at, as_of_u)]
        con = duckdb.connect(":memory:")
        try:
            con.execute("SET enable_external_access=false")
            con.execute(
                """
                CREATE TABLE news (
                    event_id VARCHAR,
                    class VARCHAR,
                    event_time TIMESTAMPTZ,
                    known_at TIMESTAMPTZ,
                    assets VARCHAR,
                    raw VARCHAR,
                    our_reaction_coef DOUBLE
                )
                """
            )
            if visible:
                con.executemany(
                    "INSERT INTO news VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r.event_id,
                            r.event_class,
                            r.event_time,
                            r.known_at,
                            ";".join(r.assets),
                            r.raw,
                            r.our_reaction_coef,
                        )
                        for r in visible
                    ],
                )
            result = con.execute(sql)
            columns = [d[0] for d in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        finally:
            con.close()
