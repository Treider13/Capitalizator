"""1.8.1 — why there was no trade. Empty file is empty, not a fake skip week."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from capitalizator.types import require_utc


@dataclass(frozen=True)
class Skip:
    reason: str
    ts: datetime


class SkipLog:
    def __init__(self) -> None:
        self.rows: list[Skip] = []

    def add(self, reason: str, ts: datetime) -> Skip:
        if not reason.strip():
            raise ValueError("skip reason is empty")
        row = Skip(reason=reason.strip(), ts=require_utc(ts))
        self.rows.append(row)
        return row

    def last_days(self, days: int, *, now: datetime) -> list[Skip]:
        if days <= 0:
            raise ValueError("days must be > 0")
        end = require_utc(now)
        start = end - timedelta(days=days)
        return [row for row in self.rows if start <= row.ts <= end]
