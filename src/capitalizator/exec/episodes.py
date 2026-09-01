"""1.6.6 — paper episode rows. Empty is honest. No Excel, no invented fills."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

MODES = frozenset({"shadow", "demo", "micro", "live"})
REQUIRED = ("trade_id", "mode", "zone_id", "gesture", "fill", "slip", "fees", "r")


class EpisodeLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(self, row: dict[str, Any]) -> dict[str, Any]:
        missing = [k for k in REQUIRED if k not in row]
        if missing:
            raise ValueError(f"episode missing: {missing}")
        if row["mode"] not in MODES:
            raise ValueError(
                f"episode.mode must be shadow|demo|micro|live, got {row['mode']!r}"
            )
        if not isinstance(row["fill"], datetime):
            raise TypeError("episode.fill must be a datetime")
        self.rows.append(dict(row))
        return self.rows[-1]

    def for_date(self, day: date) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self.rows:
            fill = row["fill"]
            if fill.date() == day:
                out.append(row)
        return out
