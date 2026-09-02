"""2.11.7 — 24h pre CPI/FOMC and 14:00–15:00 ET on CPI/FOMC days. Off until enabled.

Numbers come from infra/time.yaml. SessionWindow does not call this.
Does not open size. Does not invent a calendar row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.risk.session import load_time_config
from capitalizator.types import require_utc

PRE_CLASSES = frozenset({"CPI", "FOMC"})


@dataclass(frozen=True)
class MacroDecision:
    allow: bool
    size_mult: Decimal
    reason: str


class MacroRules:
    def __init__(self, *, enabled: bool = False) -> None:
        cfg = load_time_config()
        self.enabled = enabled
        self.pre_hours = int(cfg["pre_event_hours"])
        self.size_mult = Decimal(str(cfg["pre_event_size_mult"]))
        blackout = cfg["fomc_blackout_et"]
        self.blackout_start = time.fromisoformat(str(blackout["start"]))
        self.blackout_end = time.fromisoformat(str(blackout["end"]))
        self.ny = ZoneInfo(str(cfg["us_tz"]))
        # D-22: per-class windows around the actual release time (time.yaml, sourced).
        raw_windows = cfg.get("event_windows") or {}
        self.event_windows: dict[str, tuple[timedelta, timedelta]] = {}
        for klass, body in raw_windows.items():
            pre = int(body["pre_min"])
            post = int(body["post_min"])
            if pre < 0 or post < 0:
                raise ValueError("event_windows minutes must be >= 0")
            self.event_windows[str(klass)] = (timedelta(minutes=pre), timedelta(minutes=post))

    def decide(self, now: datetime, calendar: Sequence[NewsRow]) -> MacroDecision:
        when = require_utc(now)
        if not self.enabled:
            return MacroDecision(True, Decimal("1"), "macro_off")
        if self._et_blackout(when, calendar):
            return MacroDecision(False, Decimal("0"), "et_blackout")
        hit = self._event_window(when, calendar)
        if hit is not None:
            return MacroDecision(False, Decimal("0"), f"event_window_{hit}")
        if self._pre_event(when, calendar):
            return MacroDecision(True, self.size_mult, "pre_event")
        return MacroDecision(True, Decimal("1"), "ok")

    def _known(self, row: NewsRow, when: datetime) -> bool:
        return row.known_at <= when

    def _event_window(self, when: datetime, calendar: Sequence[NewsRow]) -> str | None:
        """Inside [event_time − pre, event_time + post] of a known row → its class."""
        for row in calendar:
            window = self.event_windows.get(row.event_class)
            if window is None or not self._known(row, when):
                continue
            pre, post = window
            if row.event_time - pre <= when <= row.event_time + post:
                return row.event_class
        return None

    def _et_blackout(self, when: datetime, calendar: Sequence[NewsRow]) -> bool:
        """14:00–15:00 ET on an FOMC day (statement 14:00, presser 14:30).

        Was applied to CPI days too; CPI prints 08:30 ET, so that window matched
        nothing real (D-22). CPI/NFP/PCE are covered by event_windows.
        """
        ny_day = when.astimezone(self.ny).date()
        stamp = when.astimezone(self.ny).timetz().replace(tzinfo=None)
        if not (self.blackout_start <= stamp < self.blackout_end):
            return False
        return any(
            row.event_class == "FOMC"
            and self._known(row, when)
            and row.event_time.astimezone(self.ny).date() == ny_day
            for row in calendar
        )

    def _pre_event(self, when: datetime, calendar: Sequence[NewsRow]) -> bool:
        window = timedelta(hours=self.pre_hours)
        for row in calendar:
            if row.event_class not in PRE_CLASSES or not self._known(row, when):
                continue
            delta = row.event_time - when
            if timedelta(0) < delta <= window:
                return True
        return False
