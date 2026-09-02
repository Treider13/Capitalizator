"""Mirror — ОКО attacks its own Shadow before it is allowed to say +1.

Real touch windows are replayed with one synthetic manipulation injected:
  spoof     one wall = 2× zone-side depth at the best price, added at t0+a,
            gone at t0+p, no prints at that price
  layering  four half-depth walls on consecutive prices, same life
  cascade   forty one-way prints at 8× the Passport rate, price walking
            ≥ 4× the normal window range, zone-side depth cut to 20% at the end
Shadow must label the injected window as injected. Detection rate per kind
over ≥5 windows must be ≥ 0.8 for `passed`. Cascade needs a mature Passport;
until then its rate is None and does not block the pass.

random.Random(seed) chooses side and offsets. Same windows + seed → same report.
`clean_alarms` counts un-injected windows Shadow did not call CLEAN — a note,
not a false-alarm rate: a real window may really be manipulated.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from capitalizator.book.reconstruct import Book, _canon
from capitalizator.book.wall_watch import WallEvent
from capitalizator.oko.passport import Passport
from capitalizator.oko.retina import RawWindow, frame
from capitalizator.oko.shadow import ShadowReport, report
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zlg.gesture import BookAdd

MIN_WINDOWS = 5
PASS_RATE = 0.8
SPOOF_SHARE = Decimal("2")
LAYER_LEVELS = 4
LAYER_SHARE = Decimal("0.5")
CASCADE_PRINTS = 40
CASCADE_RATE_MULT = Decimal("8")
CASCADE_DEPTH_LEFT = Decimal("0.2")
CASCADE_RANGE_MULT = Decimal("4")
OFFSETS_S = ((1, 3), (1, 4), (2, 5), (2, 6))


@dataclass(frozen=True)
class MirrorReport:
    n_windows: int
    spoof_hits: int
    layering_hits: int
    cascade_n: int
    cascade_hits: int
    clean_alarms: int
    seed: int
    ran_at: str

    def rate(self, kind: str) -> float | None:
        if kind == "spoof":
            return self.spoof_hits / self.n_windows if self.n_windows else None
        if kind == "layering":
            return self.layering_hits / self.n_windows if self.n_windows else None
        if kind == "cascade":
            return self.cascade_hits / self.cascade_n if self.cascade_n else None
        raise ValueError(f"unknown kind: {kind!r}")

    @property
    def passed(self) -> bool:
        if self.n_windows < MIN_WINDOWS:
            return False
        spoof = self.rate("spoof")
        layering = self.rate("layering")
        cascade = self.rate("cascade")
        if spoof is None or layering is None:
            return False
        if spoof < PASS_RATE or layering < PASS_RATE:
            return False
        return cascade is None or cascade >= PASS_RATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_windows": self.n_windows,
            "spoof_hits": self.spoof_hits,
            "layering_hits": self.layering_hits,
            "cascade_n": self.cascade_n,
            "cascade_hits": self.cascade_hits,
            "clean_alarms": self.clean_alarms,
            "seed": self.seed,
            "ran_at": self.ran_at,
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MirrorReport:
        return cls(
            n_windows=int(raw["n_windows"]),
            spoof_hits=int(raw["spoof_hits"]),
            layering_hits=int(raw["layering_hits"]),
            cascade_n=int(raw["cascade_n"]),
            cascade_hits=int(raw["cascade_hits"]),
            clean_alarms=int(raw["clean_alarms"]),
            seed=int(raw["seed"]),
            ran_at=str(raw["ran_at"]),
        )


def run(
    windows: Iterable[RawWindow],
    passport_for: Callable[[str], Passport],
    *,
    seed: int,
    now: datetime,
) -> MirrorReport:
    rng = random.Random(seed)
    n = spoof_hits = layering_hits = cascade_n = cascade_hits = clean_alarms = 0
    for raw in windows:
        passport = passport_for(raw.symbol)
        n += 1
        side = rng.choice(("zone", "opp"))
        at_s, pull_s = rng.choice(OFFSETS_S)
        clean = _shadow(raw, passport)
        if clean.label not in {"CLEAN", "UNKNOWN"}:
            clean_alarms += 1
        spoofed = _shadow(inject_spoof(raw, side=side, at_s=at_s, pull_s=pull_s), passport)
        if spoofed.label == "SPOOF" and spoofed.spoof_side == side:
            spoof_hits += 1
        layered = _shadow(inject_layering(raw, side=side, at_s=at_s, pull_s=pull_s), passport)
        if layered.label == "LAYERING":
            layering_hits += 1
        if passport.mature:
            cascade_n += 1
            if _shadow(inject_cascade(raw, passport), passport).label == "CASCADE":
                cascade_hits += 1
    return MirrorReport(
        n_windows=n,
        spoof_hits=spoof_hits,
        layering_hits=layering_hits,
        cascade_n=cascade_n,
        cascade_hits=cascade_hits,
        clean_alarms=clean_alarms,
        seed=seed,
        ran_at=require_utc(now).isoformat(),
    )


def _shadow(raw: RawWindow, passport: Passport) -> ShadowReport:
    return report(raw, frame(raw, passport))


def inject_spoof(
    raw: RawWindow, *, side: str, at_s: int, pull_s: int, share: Decimal = SPOOF_SHARE
) -> RawWindow:
    book_side = _book_side(raw, side)
    depth = _depth(raw, book_side)
    px = _anchor_px(raw, book_side)
    qty = depth * share
    if qty <= 0:
        qty = raw.tick_size
    return _inject_walls(raw, book_side, ((px, qty),), at_s=at_s, pull_s=pull_s)


def inject_layering(
    raw: RawWindow,
    *,
    side: str,
    at_s: int,
    pull_s: int,
    levels: int = LAYER_LEVELS,
    share: Decimal = LAYER_SHARE,
) -> RawWindow:
    book_side = _book_side(raw, side)
    depth = _depth(raw, book_side)
    anchor = _anchor_px(raw, book_side)
    step = -raw.tick_size if book_side == "bid" else raw.tick_size
    qty = depth * share
    if qty <= 0:
        qty = raw.tick_size
    walls = tuple((anchor + step * i, qty) for i in range(levels))
    return _inject_walls(raw, book_side, walls, at_s=at_s, pull_s=pull_s)


def inject_cascade(
    raw: RawWindow, passport: Passport, *, n_prints: int = CASCADE_PRINTS
) -> RawWindow:
    """One-way prints hitting the zone, price walking away, depth collapsing."""
    if not passport.mature:
        raise ValueError("cascade injection needs a mature passport")
    med_qty = passport.print_qty.median()
    med_rate = passport.prints_per_s.median()
    med_range = passport.range_ticks.median()
    assert med_qty is not None and med_rate is not None and med_range is not None
    rate = max(med_rate * CASCADE_RATE_MULT, Decimal(n_prints) / Decimal(raw.window_s))
    step_s = Decimal("1") / rate
    # Walk far enough that the range is ≥ CASCADE_RANGE_MULT × the normal window range.
    ticks_total = max(Decimal(n_prints), med_range * CASCADE_RANGE_MULT)
    step_ticks = int((ticks_total / n_prints).to_integral_value(rounding="ROUND_CEILING"))
    step_ticks = max(1, step_ticks)
    side = raw.zone_side
    taker = "sell" if side == "bid" else "buy"
    direction = -raw.tick_size if side == "bid" else raw.tick_size
    start_px = _anchor_px(raw, side)
    prints: list[MarketEvent] = []
    last_ts = raw.t0
    for i in range(n_prints):
        offset = step_s * (i + 1)
        if offset >= raw.window_s:
            break
        ts = raw.t0 + timedelta(microseconds=int(offset * 1_000_000))
        last_ts = ts
        px = start_px + direction * step_ticks * i
        if px <= 0:
            break
        prints.append(
            MarketEvent(
                stream="trades",
                exchange=raw.trades[0].exchange if raw.trades else "bybit",
                symbol=raw.symbol,
                exchange_ts=ts,
                recv_ts=ts,
                payload={"px": _canon(px), "qty": _canon(med_qty * 2), "side": taker},
            )
        )
    end_base = raw.book_end()
    collapsed = end_base
    center = raw.center
    width = raw.tick_size * raw.delta_ticks
    for level_px, size in end_base.levels(side).items():
        if abs(level_px - center) <= width:
            collapsed = collapsed.with_level(side, level_px, size * CASCADE_DEPTH_LEFT)
    end_ts = max(last_ts, raw.t_end - timedelta(microseconds=1))
    path = tuple((ts, b) for ts, b in raw.book_path if require_utc(ts) < end_ts)
    path = (*path, (end_ts, collapsed))
    trades = tuple(sorted((*raw.trades, *prints), key=lambda t: t.exchange_ts))
    return RawWindow(
        symbol=raw.symbol,
        zone=raw.zone,
        t0=raw.t0,
        window_s=raw.window_s,
        tick_size=raw.tick_size,
        delta_ticks=raw.delta_ticks,
        book_pre=raw.book_pre,
        book_path=path,
        trades=trades,
        adds=raw.adds,
        wall_events=raw.wall_events,
    )


def _inject_walls(
    raw: RawWindow,
    side: str,
    walls: tuple[tuple[Decimal, Decimal], ...],
    *,
    at_s: int,
    pull_s: int,
) -> RawWindow:
    if not 0 < at_s < pull_s <= raw.window_s:
        raise ValueError("need 0 < at_s < pull_s <= window_s")
    t_add = raw.t0 + timedelta(seconds=at_s)
    t_pull = raw.t0 + timedelta(seconds=pull_s)
    original = [(require_utc(ts), b) for ts, b in raw.book_path]

    def base_at(when: datetime) -> Book:
        prior = [b for ts, b in original if ts <= when]
        return prior[-1] if prior else raw.book_pre

    def stacked(book: Book) -> Book:
        out = book
        for px, qty in walls:
            out = out.with_level(side, px, out.level(side, str(px)) + qty)
        return out

    path: list[tuple[datetime, Book]] = []
    for ts, book in original:
        if ts < t_add or ts >= t_pull:
            path.append((ts, book))
        else:
            path.append((ts, stacked(book)))
    if not any(ts == t_add for ts, _ in original):
        path.append((t_add, stacked(base_at(t_add))))
    if not any(ts == t_pull for ts, _ in original):
        path.append((t_pull, base_at(t_pull)))
    path.sort(key=lambda row: row[0])
    adds = tuple(
        sorted(
            (*raw.adds, *(BookAdd(ts=t_add, side=side, px=px, qty=qty) for px, qty in walls)),
            key=lambda a: a.ts,
        )
    )
    events = list(raw.wall_events)
    for px, qty in walls:
        events.append(
            WallEvent(
                symbol=raw.symbol, px=_canon(px), side=side, size=qty, kind="appeared", ts=t_add
            )
        )
        events.append(
            WallEvent(
                symbol=raw.symbol, px=_canon(px), side=side, size=qty, kind="pulled", ts=t_pull
            )
        )
    events.sort(key=lambda e: e.ts)
    return RawWindow(
        symbol=raw.symbol,
        zone=raw.zone,
        t0=raw.t0,
        window_s=raw.window_s,
        tick_size=raw.tick_size,
        delta_ticks=raw.delta_ticks,
        book_pre=raw.book_pre,
        book_path=tuple(path),
        trades=raw.trades,
        adds=adds,
        wall_events=tuple(events),
    )


def _book_side(raw: RawWindow, side: str) -> str:
    if side == "zone":
        return raw.zone_side
    if side == "opp":
        return raw.opp_side
    raise ValueError("side must be zone|opp")


def _depth(raw: RawWindow, book_side: str) -> Decimal:
    return raw.book_pre.depth_near(book_side, str(raw.center), raw.delta_ticks)


def _anchor_px(raw: RawWindow, book_side: str) -> Decimal:
    bid, ask = raw.book_pre.best()
    if book_side == "bid":
        return bid if bid is not None else raw.zone.lo
    return ask if ask is not None else raw.zone.hi
