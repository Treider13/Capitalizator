"""Footprint (След) — is someone *building a position* in this window.

A whale on Bybit is not an object, it is a trace. Five traces we can measure
on public data, all relative to the Passport (INVENTION-OKO §След):

  BUILD_LONG / BUILD_SHORT   ΔOI over the window ≥ 2 robust σ up, direction by
                             the mid move (aggression if the mid stood still)
  UNWIND                     ΔOI ≤ −2 robust σ — positions are being closed
  ICEBERG                    one price executed ≥ 2× the most it ever showed and
                             refilled ≥ 2 times inside the window
  ABSORB                     one-way takers ≥ 3× the normal window volume,
                             |aggression| ≥ 0.7, mid moved ≤ 1 tick, depth held
  SWEEP                      one print ≥ 5× the median, or ≥ 3× the normal range
                             in ≤ 5 prints (direction, not a position fact)
  NONE                       nothing above

`side` is the side of the book the *participant* sits on: buyer → bid,
seller → ask. For ABSORB it is the passive side that took the flow; for
ICEBERG the refilled side; for BUILD the direction; for SWEEP the aggressor.
Liquidations are evidence (long/short qty vs median print), not a label:
Shadow already names a CASCADE from the tape.

A Footprint never gives +1 by itself. It widens the Forecast class key and can
say −1 when position-building evidence points against the idea. SWEEP is too
ambiguous (stop run or entry) to vote; it is written and learned.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from capitalizator.oko.retina import RawWindow, RetinaFrame
from capitalizator.oko.shadow import FINGERPRINT_LEN as SHADOW_FP_LEN
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import require_utc

FootprintLabel = Literal[
    "BUILD_LONG", "BUILD_SHORT", "UNWIND", "ICEBERG", "ABSORB", "SWEEP", "NONE"
]
FOOTPRINT_LABELS: tuple[str, ...] = (
    "NONE",
    "BUILD_LONG",
    "BUILD_SHORT",
    "UNWIND",
    "ICEBERG",
    "ABSORB",
    "SWEEP",
)
VOTING_LABELS = frozenset({"BUILD_LONG", "BUILD_SHORT", "ICEBERG", "ABSORB"})
FootSide = Literal["bid", "ask"]

OI_Z = Decimal("2")
ICEBERG_EXEC_MULT = Decimal("2")
ICEBERG_MIN_REFILLS = 2
ABSORB_MIN_PRINTS = 10
ABSORB_AGGRESSION = Decimal("0.7")
ABSORB_VOLUME_REL = Decimal("3")
ABSORB_MAX_MID_TICKS = Decimal("1")
ABSORB_MIN_DEPTH_RATIO = Decimal("0.8")
SWEEP_PRINT_REL = Decimal("5")
SWEEP_RANGE_REL = Decimal("3")
SWEEP_MAX_PRINTS = 5
LIQ_HEAVY_REL = Decimal("5")
FOOTPRINT_FP_LEN = 3
FINGERPRINT_LEN = SHADOW_FP_LEN + FOOTPRINT_FP_LEN


@dataclass(frozen=True)
class FootprintReport:
    label: FootprintLabel
    side: FootSide | None
    oi_delta_frac: Decimal | None
    oi_z: Decimal | None
    iceberg_ratio: Decimal | None
    iceberg_refills: int
    taker_volume_rel: Decimal | None
    liq_rel: Decimal | None
    liq_dominant: Literal["long", "short"] | None
    fingerprint: tuple[int, ...]
    evidence: dict[str, str]

    def __post_init__(self) -> None:
        if self.label not in FOOTPRINT_LABELS:
            raise ValueError(f"unknown footprint label: {self.label!r}")
        if self.side not in (None, "bid", "ask"):
            raise ValueError("footprint side must be bid|ask|None")
        if len(self.fingerprint) != FOOTPRINT_FP_LEN:
            raise ValueError("footprint fingerprint length")
        if self.label == "UNWIND" and self.side is not None:
            raise ValueError("UNWIND has no side")
        if self.label == "NONE" and self.side is not None:
            raise ValueError("NONE has no side")

    @property
    def votes(self) -> bool:
        return self.label in VOTING_LABELS and self.side is not None


def needed_side(*, idea: str, zone_side: str) -> FootSide:
    """Which builder helps the idea: bounce wants the zone side, a break wants the other."""
    if zone_side not in {"support", "resistance"}:
        raise ValueError("zone_side must be support|resistance")
    zone_book: FootSide = "bid" if zone_side == "support" else "ask"
    opp: FootSide = "ask" if zone_book == "bid" else "bid"
    if idea in {"bounce", "spring", "failed_break"}:
        return zone_book
    if idea == "breakout":
        return opp
    raise ValueError("idea must be bounce|spring|breakout|failed_break")


def report(raw: RawWindow, frame: RetinaFrame) -> FootprintReport:
    prints = raw.prints()
    inside = [(ts, b) for ts, b in raw.book_path if raw.t0 < require_utc(ts) <= raw.t_end]

    build = _build(raw, frame)
    iceberg_side, iceberg_ratio, iceberg_refills = _iceberg(raw, prints, inside)
    absorb_side = _absorb(raw, frame)
    sweep_side = _sweep(raw, frame)

    label: FootprintLabel
    side: FootSide | None
    if build is not None:
        label, side = build
    elif iceberg_side is not None:
        label, side = "ICEBERG", iceberg_side
    elif absorb_side is not None:
        label, side = "ABSORB", absorb_side
    elif sweep_side is not None:
        label, side = "SWEEP", sweep_side
    else:
        label, side = "NONE", None

    liq_dominant: Literal["long", "short"] | None = None
    if frame.liq_long_qty > frame.liq_short_qty:
        liq_dominant = "long"
    elif frame.liq_short_qty > frame.liq_long_qty:
        liq_dominant = "short"

    fingerprint = (
        FOOTPRINT_LABELS.index(label),
        0 if side is None else (1 if side == "bid" else 2),
        _liq_bucket(frame.liq_rel),
    )
    evidence = {
        "oi_before": _dec(frame.oi_before),
        "oi_after": _dec(frame.oi_after),
        "iceberg_side": iceberg_side or "",
        "absorb_side": absorb_side or "",
        "sweep_side": sweep_side or "",
        "liq_long": _dec(frame.liq_long_qty),
        "liq_short": _dec(frame.liq_short_qty),
    }
    return FootprintReport(
        label=label,
        side=side,
        oi_delta_frac=frame.oi_delta_frac,
        oi_z=frame.oi_z,
        iceberg_ratio=iceberg_ratio,
        iceberg_refills=iceberg_refills,
        taker_volume_rel=frame.taker_volume_rel,
        liq_rel=frame.liq_rel,
        liq_dominant=liq_dominant,
        fingerprint=fingerprint,
        evidence=evidence,
    )


def combined_fingerprint(shadow_fp: tuple[int, ...], foot: FootprintReport) -> tuple[int, ...]:
    if len(shadow_fp) != SHADOW_FP_LEN:
        raise ValueError("shadow fingerprint length")
    return (*shadow_fp, *foot.fingerprint)


def _build(raw: RawWindow, frame: RetinaFrame) -> tuple[FootprintLabel, FootSide | None] | None:
    if frame.oi_z is None:
        return None
    if frame.oi_z <= -OI_Z:
        return "UNWIND", None
    if frame.oi_z < OI_Z:
        return None
    direction = _direction(raw, frame)
    if direction is None:
        return None
    return ("BUILD_LONG", "bid") if direction > 0 else ("BUILD_SHORT", "ask")


def _direction(raw: RawWindow, frame: RetinaFrame) -> int | None:
    """+1 up / −1 down from the mid; aggression breaks a still mid. None = unknown.

    Pressure is takers *into* the zone: sellers into support push down, buyers
    into resistance push up. aggression > 0 means pressure won.
    """
    if frame.mid_move_ticks is not None and frame.mid_move_ticks != 0:
        return 1 if frame.mid_move_ticks > 0 else -1
    if frame.aggression is None or frame.aggression == 0:
        return None
    into_zone = -1 if raw.zone.side == "support" else 1
    return into_zone if frame.aggression > 0 else -into_zone


def _iceberg(
    raw: RawWindow, prints: list, inside: list
) -> tuple[FootSide | None, Decimal | None, int]:
    if len(inside) < 2 or not prints:
        return None, None, 0
    clf = TapeClassifier()
    executed: dict[tuple[str, Decimal], Decimal] = defaultdict(lambda: Decimal("0"))
    for trade in prints:
        taker = clf.taker_side(trade)
        hit: FootSide = "bid" if taker == "sell" else "ask"
        executed[(hit, Decimal(str(trade.payload["px"])))] += Decimal(str(trade.payload["qty"]))
    books = [raw.book_pre, *(b for _, b in inside)]
    best_side: FootSide | None = None
    best_ratio: Decimal | None = None
    best_refills = 0
    for (side, px), done in executed.items():
        levels = [b.level(side, str(px)) for b in books]
        shown = max(levels)
        if shown <= 0:
            continue
        refills = sum(1 for a, b in zip(levels, levels[1:], strict=False) if b > a)
        ratio = done / shown
        if ratio >= ICEBERG_EXEC_MULT and refills >= ICEBERG_MIN_REFILLS:
            if best_ratio is None or ratio > best_ratio:
                best_side, best_ratio, best_refills = side, ratio, refills
    return best_side, best_ratio, best_refills


def _absorb(raw: RawWindow, frame: RetinaFrame) -> FootSide | None:
    if frame.n_prints < ABSORB_MIN_PRINTS:
        return None
    if frame.aggression is None or frame.taker_volume_rel is None:
        return None
    if frame.mid_move_ticks is None or frame.depth_end_ratio is None:
        return None
    if abs(frame.aggression) < ABSORB_AGGRESSION:
        return None
    if frame.taker_volume_rel < ABSORB_VOLUME_REL:
        return None
    if abs(frame.mid_move_ticks) > ABSORB_MAX_MID_TICKS:
        return None
    if frame.depth_end_ratio < ABSORB_MIN_DEPTH_RATIO:
        return None
    # Pressure = takers hitting the zone side; the absorber is that side.
    return raw.zone_side if frame.aggression > 0 else raw.opp_side  # type: ignore[return-value]


def _sweep(raw: RawWindow, frame: RetinaFrame) -> FootSide | None:
    big_print = frame.max_print_rel is not None and frame.max_print_rel >= SWEEP_PRINT_REL
    wide_fast = (
        frame.range_rel is not None
        and frame.range_rel >= SWEEP_RANGE_REL
        and 2 <= frame.n_prints <= SWEEP_MAX_PRINTS
    )
    if not (big_print or wide_fast):
        return None
    if frame.aggression is None or frame.aggression == 0:
        return None
    # Aggressor into the zone side sits on the other side of the market.
    return raw.opp_side if frame.aggression > 0 else raw.zone_side  # type: ignore[return-value]


def _liq_bucket(liq_rel: Decimal | None) -> int:
    if liq_rel is None:
        return 3
    if liq_rel <= 0:
        return 0
    return 2 if liq_rel >= LIQ_HEAVY_REL else 1


def _dec(x: Decimal | None) -> str:
    return "" if x is None else format(x.normalize(), "f")
