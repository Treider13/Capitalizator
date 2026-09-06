"""0.3.6 — Zone Liquidity Gesture. Log only. No size.

INVENTION-FIRST-FACT.md: four buckets in (t, t+T], T = zlg_window_s.
SILENCE if max A < γ·q or the argmax is a tie.

What fills a bucket (jury §3.2, 2026-09-03): **liquidity that survived**, not
liquidity that was shown. A quote added and pulled inside the window contributes
nothing — 97% of resting orders are cancelled before they trade, and a spoof is
exactly "add, then pull". A quote *executed* against (prints at its price) is not
a pull: it stood and absorbed. Survivors are weighted by how long they stood
(`MIN_ALIVE_S` seconds for full credit), so a quote flashed at t+7.9 s cannot
carry a DEFEND on its own. The Shadow (ОКО) still names the spoof; this makes the
gesture itself hard to fake.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from capitalizator.memory.registry import Touch
from capitalizator.types import require_utc
from capitalizator.zones.config import RegistryConfig, load_registry

Gesture = Literal["DEFEND", "RETREAT", "IMPROVE", "FADE", "SILENCE"]
BookSide = Literal["bid", "ask"]


@dataclass(frozen=True)
class BookAdd:
    ts: datetime
    side: BookSide
    px: Decimal
    qty: Decimal

    def __post_init__(self) -> None:
        require_utc(self.ts)
        if self.qty <= 0:
            raise ValueError("add qty must be > 0")


@dataclass(frozen=True)
class BookPull:
    """A size reduction at a price inside the window. `qty` > 0 = amount removed."""

    ts: datetime
    side: BookSide
    px: Decimal
    qty: Decimal

    def __post_init__(self) -> None:
        require_utc(self.ts)
        if self.qty <= 0:
            raise ValueError("pull qty must be > 0")


# An add needs this long alive inside the window for full credit; younger survivors
# are pro-rated. Provenance: design choice (Shadow flags sub-second flashes), not data.
MIN_ALIVE_S = 2.0
# A reduction within this many ms after a print at the same price is execution, not a pull.
PRINT_GRACE_MS = 250


def survived_adds(
    adds: Sequence[BookAdd],
    pulls: Sequence[BookPull],
    prints: Sequence[tuple[datetime, Decimal] | tuple[datetime, Decimal, Decimal]],
    *,
    t0: datetime,
    t1: datetime,
    min_alive_s: float = MIN_ALIVE_S,
) -> list[tuple[BookAdd, Decimal]]:
    """Net adds against pulls per (side, price), LIFO (the freshest quote is the one a
    spoofer pulls); a pull is explained by prints at that price within ±PRINT_GRACE_MS
    only up to the printed VOLUME (a 0.01 print does not launder a 500-lot pull —
    audit B7); what is left is weighted by time alive. Prints may be (ts, px) — legacy,
    treated as unbounded volume — or (ts, px, qty)."""
    window = (t1 - t0).total_seconds()
    if window <= 0:
        return []
    in_adds = [a for a in adds if t0 < require_utc(a.ts) <= t1]
    in_pulls = [p for p in pulls if t0 < require_utc(p.ts) <= t1]
    prints_by_px: dict[Decimal, list[tuple[datetime, Decimal | None]]] = {}
    for row in prints:
        ts, px = row[0], row[1]
        qty = row[2] if len(row) > 2 else None
        prints_by_px.setdefault(px, []).append((require_utc(ts), qty))
    remaining: dict[int, Decimal] = {i: a.qty for i, a in enumerate(in_adds)}
    by_level: dict[tuple[str, Decimal], list[tuple[datetime, int]]] = {}
    for i, a in enumerate(in_adds):
        by_level.setdefault((a.side, a.px), []).append((require_utc(a.ts), i))
    grace = timedelta(milliseconds=PRINT_GRACE_MS)
    for pull in sorted(in_pulls, key=lambda p: p.ts):
        pts = require_utc(pull.ts)
        near = [
            q for t, q in prints_by_px.get(pull.px, ()) if pts - grace <= t <= pts + grace
        ]
        if any(q is None for q in near):
            continue  # legacy prints without volume: executed, not pulled
        executed = sum((q for q in near if q is not None), Decimal("0"))
        left = pull.qty - executed  # only the unexplained part is a pull
        if left <= 0:
            continue
        stack = [(ts, i) for ts, i in by_level.get((pull.side, pull.px), ()) if ts <= pts]
        for _ts, i in sorted(stack, key=lambda x: x[0], reverse=True):
            if left <= 0:
                break
            take = min(remaining[i], left)
            remaining[i] -= take
            left -= take
    out: list[tuple[BookAdd, Decimal]] = []
    for i, a in enumerate(in_adds):
        if remaining[i] <= 0:
            continue
        alive = (t1 - require_utc(a.ts)).total_seconds()
        weight = Decimal(str(min(1.0, alive / min_alive_s))) if min_alive_s > 0 else Decimal("1")
        eff = remaining[i] * weight
        if eff > 0:
            out.append((a, eff))
    return out


@dataclass(frozen=True)
class GestureResult:
    gesture: Gesture
    a_same: Decimal
    a_back: Decimal
    a_in: Decimal
    a_opp: Decimal


class ZLG:
    def __init__(self, *, tick_size: Decimal, config: RegistryConfig | None = None) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        self.tick_size = tick_size
        self.config = config or load_registry()

    def classify(
        self,
        touch: Touch,
        book_adds: Sequence[BookAdd],
        q: Decimal,
        *,
        hit_side: BookSide,
        mid: Decimal,
        opp_best: Decimal,
        book_ready: bool = True,
        tick: Decimal | None = None,
        book_pulls: Sequence[BookPull] = (),
        prints: Sequence[tuple[datetime, Decimal]] = (),
    ) -> GestureResult:
        """`tick` overrides the constructor tick for this symbol (instruments-info).
        `book_pulls` / `prints` turn shown liquidity into survived liquidity; without
        them (legacy callers, fixtures) every add counts in full."""
        if q <= 0:
            raise ValueError("q must be > 0")
        if tick is not None and tick <= 0:
            raise ValueError("tick must be > 0")
        if (not book_ready) or mid == touch.trade_px:
            return GestureResult(
                gesture="SILENCE",
                a_same=Decimal("0"),
                a_back=Decimal("0"),
                a_in=Decimal("0"),
                a_opp=Decimal("0"),
            )
        t0 = require_utc(touch.ts)
        t1 = t0 + timedelta(seconds=self.config.zlg_window_s)
        a_same = a_back = a_in = a_opp = Decimal("0")
        one = tick if tick is not None else self.tick_size
        delta = one * self.config.prs_delta_ticks
        opp: BookSide = "ask" if hit_side == "bid" else "bid"
        if book_pulls or prints:
            weighted = survived_adds(book_adds, book_pulls, prints, t0=t0, t1=t1)
        else:
            weighted = [
                (a, a.qty) for a in book_adds if t0 < require_utc(a.ts) <= t1
            ]
        for add, qty in weighted:
            if add.side == opp:
                if abs(add.px - opp_best) <= delta:
                    a_opp += qty
                continue
            if add.side != hit_side:
                continue
            if abs(add.px - touch.trade_px) <= one:
                a_same += qty
                continue
            toward_mid = (add.px - touch.trade_px) * (mid - touch.trade_px)
            if toward_mid > 0:
                a_in += qty
            else:
                a_back += qty
        buckets: dict[Gesture, Decimal] = {
            "DEFEND": a_same,
            "RETREAT": a_back,
            "IMPROVE": a_in,
            "FADE": a_opp,
        }
        peak = max(buckets.values())
        winners = [name for name, value in buckets.items() if value == peak]
        gamma_q = Decimal(str(self.config.zlg_gamma)) * q
        gesture: Gesture = "SILENCE"
        if peak >= gamma_q and len(winners) == 1:
            gesture = winners[0]
        return GestureResult(
            gesture=gesture,
            a_same=a_same,
            a_back=a_back,
            a_in=a_in,
            a_opp=a_opp,
        )
