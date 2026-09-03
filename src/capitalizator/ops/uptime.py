"""Tape uptime, tracked incrementally (F0 «сутки без немаркированной дыры»).

The law (PHASE-BUILD 0.1.7): 24 h of BTC trades where every hole longer than
`MAX_UNMARKED_GAP_S` is covered by a `gap` marker (ts_from/ts_to) the recorder wrote
when it (re)connected. "Silently died" = a hole nobody marked.

Before this module the console re-read the WHOLE tape on every page (`ops/contour`):
with two days of BTC+ETH that was 3 GB of JSON → the console was OOM-killed on every
`/api/status` (VPS, 2026-09-03). Now the desk feeds every trade / gap event it already
streams into `UptimeTracker` (O(1) per event), persists the state as meta
`tape_uptime`, and the console evaluates the law from that record.

`MAX_UNMARKED_GAP_S` was 0.0 in the old code: any millisecond between two prints
counted as a hole, so real tape could never turn green. 60 s is the threshold: BTC
perps print many times a second; a minute of silence is a dead feed, not a market.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from capitalizator.types import MarketEvent, require_utc

HOURS24 = 24.0
MAX_UNMARKED_GAP_S = 60.0
GAPS_KEPT = 200


@dataclass
class SymbolUptime:
    run_start: datetime | None = None  # first trade of the current unbroken stretch
    last_trade: datetime | None = None
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)  # marked holes
    unmarked_holes: int = 0
    last_unmarked: tuple[datetime, datetime] | None = None
    run_before_hole: datetime | None = None  # run_start the last unmarked hole broke
    trades: int = 0

    def covered(self, lo: datetime, hi: datetime) -> bool:
        return any(g_lo <= lo and g_hi >= hi for g_lo, g_hi in self.gaps)

    def on_gap(self, lo: datetime, hi: datetime) -> None:
        self.gaps.append((lo, hi))
        if len(self.gaps) > GAPS_KEPT:
            del self.gaps[: -GAPS_KEPT]
        # a marker may arrive after the trade that closed the hole (file order):
        # a stretch broken by that very hole is healed
        last = self.last_unmarked
        if last is not None and lo <= last[0] and hi >= last[1]:
            self.last_unmarked = None
            self.unmarked_holes = max(0, self.unmarked_holes - 1)
            if self.run_before_hole is not None:
                self.run_start = self.run_before_hole  # the stretch was never broken
                self.run_before_hole = None

    def on_trade(self, ts: datetime, *, max_unmarked_s: float) -> None:
        self.trades += 1
        if self.last_trade is None:
            self.run_start = ts
            self.last_trade = ts
            return
        if ts < self.last_trade:
            return  # out-of-order replay row: not a hole
        hole = (ts - self.last_trade).total_seconds()
        if hole > max_unmarked_s and not self.covered(self.last_trade, ts):
            self.unmarked_holes += 1
            self.last_unmarked = (self.last_trade, ts)
            self.run_before_hole = self.run_start
            self.run_start = ts  # the stretch restarts after an unmarked hole
        self.last_trade = ts

    def span_s(self) -> float | None:
        if self.run_start is None or self.last_trade is None:
            return None
        return (self.last_trade - self.run_start).total_seconds()

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_start": None if self.run_start is None else self.run_start.isoformat(),
            "last_trade": None if self.last_trade is None else self.last_trade.isoformat(),
            "gaps": [(a.isoformat(), b.isoformat()) for a, b in self.gaps[-GAPS_KEPT:]],
            "unmarked_holes": self.unmarked_holes,
            "last_unmarked": None
            if self.last_unmarked is None
            else (self.last_unmarked[0].isoformat(), self.last_unmarked[1].isoformat()),
            "run_before_hole": None
            if self.run_before_hole is None
            else self.run_before_hole.isoformat(),
            "trades": self.trades,
        }

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> SymbolUptime:
        def _dt(v: Any) -> datetime | None:
            return None if v in (None, "") else datetime.fromisoformat(str(v))

        out = cls(run_start=_dt(raw.get("run_start")), last_trade=_dt(raw.get("last_trade")))
        for pair in raw.get("gaps") or []:
            try:
                a, b = _dt(pair[0]), _dt(pair[1])
            except (TypeError, IndexError, ValueError):
                continue
            if a is not None and b is not None:
                out.gaps.append((a, b))
        out.unmarked_holes = int(raw.get("unmarked_holes") or 0)
        lu = raw.get("last_unmarked")
        if lu:
            try:
                a, b = _dt(lu[0]), _dt(lu[1])
                if a is not None and b is not None:
                    out.last_unmarked = (a, b)
            except (TypeError, IndexError, ValueError):
                pass
        out.run_before_hole = _dt(raw.get("run_before_hole"))
        out.trades = int(raw.get("trades") or 0)
        return out


@dataclass
class UptimeTracker:
    max_unmarked_s: float = MAX_UNMARKED_GAP_S
    symbols: dict[str, SymbolUptime] = field(default_factory=dict)

    def on_event(self, event: MarketEvent) -> None:
        if event.stream not in {"trades", "gap"}:
            return
        st = self.symbols.setdefault(event.symbol, SymbolUptime())
        if event.stream == "trades":
            st.on_trade(require_utc(event.exchange_ts), max_unmarked_s=self.max_unmarked_s)
            return
        raw_from, raw_to = event.payload.get("ts_from"), event.payload.get("ts_to")
        if raw_from is None or raw_to is None:
            return  # a seq gap of the book is not a time hole
        try:
            lo = require_utc(datetime.fromisoformat(str(raw_from)))
            hi = require_utc(datetime.fromisoformat(str(raw_to)))
        except (TypeError, ValueError):
            return
        if hi >= lo:
            st.on_gap(lo, hi)

    def to_json(self) -> str:
        return json.dumps(
            {sym: st.to_payload() for sym, st in sorted(self.symbols.items())}, sort_keys=True
        )

    @classmethod
    def from_json(cls, raw: str | None) -> UptimeTracker:
        out = cls()
        if not raw:
            return out
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return out
        if isinstance(data, dict):
            for sym, payload in data.items():
                if isinstance(payload, dict):
                    try:
                        out.symbols[str(sym)] = SymbolUptime.from_payload(payload)
                    except (TypeError, ValueError):
                        continue
        return out


def hours24_from_state(
    state: Mapping[str, Any] | None, *, symbol: str, hours: float = HOURS24
) -> tuple[bool, float | None, dict[str, Any]]:
    """(green, span_s, detail) for the console. Green = the current unbroken stretch of
    `symbol` trades spans ≥ `hours`. `detail` says why not, in facts."""
    if not state or symbol not in state:
        return False, None, {"reason": "no uptime record yet (desk has not seen trades)"}
    st = SymbolUptime.from_payload(state[symbol])
    span = st.span_s()
    detail: dict[str, Any] = {
        "run_start": None if st.run_start is None else st.run_start.isoformat(),
        "last_trade": None if st.last_trade is None else st.last_trade.isoformat(),
        "unmarked_holes": st.unmarked_holes,
        "marked_gaps": len(st.gaps),
        "trades": st.trades,
    }
    if span is None:
        detail["reason"] = "fewer than two trades"
        return False, None, detail
    if span + 1e-9 < hours * 3600:
        detail["reason"] = f"span {span:.0f}s < {hours * 3600:.0f}s"
        if st.last_unmarked is not None:
            detail["last_unmarked_hole"] = [
                st.last_unmarked[0].isoformat(), st.last_unmarked[1].isoformat()
            ]
        return False, span, detail
    return True, span, detail
