"""Shadow — names what the book is doing to us. L2 only, no order ids.

Bybit gives sizes per price, not per order. So Shadow infers behaviour:

- SPOOF: size added on a side inside the window that *vanished* by the end
  without prints at that price (a wall that never wanted to trade). Zone side
  = fake defence under our bounce; opposite side = a push into the zone.
  WallWatch `pulled` events in [t0 − W, t_end] are the second witness.
- LAYERING: the same vanish across ≥3 distinct prices on one side.
- CASCADE: prints far above the Passport rate, one-directional (|aggression|
  ≥ 0.8), depth collapsed (≤40% of pre), range ≥3× normal. A liquidation run.
- THIN: zone-side depth < 25% of the Passport median. The book is not there.
- UNKNOWN: no book inside the window after the print. Nothing to judge.

tape_trust: duplicated (px, qty) pairs beyond the normal share, and OFI that
points against the mid move. None when fewer than 10 prints — no evidence is
not trust. book_trust ∈ [0, 1]: 1 − the strongest of the signs above.
fingerprint: quantised ints for the immune Memory. Same window → same tuple.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from capitalizator.book.reconstruct import Book
from capitalizator.oko.retina import RawWindow, RetinaFrame, levels_in_window
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import require_utc
from capitalizator.zlg.gesture import BookAdd

ShadowLabel = Literal["CLEAN", "SPOOF", "LAYERING", "CASCADE", "THIN", "UNKNOWN"]
SHADOW_LABELS = frozenset({"CLEAN", "SPOOF", "LAYERING", "CASCADE", "THIN", "UNKNOWN"})

ADD_MIN_SHARE = Decimal("0.10")  # an add below 10% of side depth is not a wall
SPOOF_MIN_ADD_SHARE = Decimal("0.25")  # added mass must matter vs depth to be a spoof
SPOOF_LABEL = 0.6
LAYER_MIN_LEVELS = 3
LAYER_SHARE = 0.6
LAYER_LABEL = 0.5
FLICKER_S = Decimal("2")
CASCADE_RATE_REL = Decimal("4")
CASCADE_AGGRESSION = Decimal("0.8")
CASCADE_DEPTH_RATIO = Decimal("0.4")
CASCADE_RANGE_REL = Decimal("3")
CASCADE_MIN_PRINTS = 10
THIN_DEPTH_REL = Decimal("0.25")
TAPE_MIN_PRINTS = 10
DUP_NORMAL_SHARE = 0.5
OFI_REL_MIN = Decimal("0.5")
MID_MOVE_MIN_TICKS = Decimal("2")
OFI_MISMATCH_TRUST = 0.5
THIN_PENALTY = 0.5
OPP_SPOOF_WEIGHT = 0.5
FINGERPRINT_LEN = 10


@dataclass(frozen=True)
class SideScan:
    added_qty: Decimal
    vanished_qty: Decimal
    levels_added: int
    levels_vanished: int
    flicker_n: int
    pulled_qty: Decimal
    eaten_qty: Decimal

    @property
    def vanished_share(self) -> float:
        if self.added_qty <= 0:
            return 0.0
        return float(self.vanished_qty / self.added_qty)


@dataclass(frozen=True)
class ShadowReport:
    label: ShadowLabel
    spoof_side: Literal["zone", "opp"] | None
    spoof_score: float
    opp_spoof_score: float
    layering_score: float
    layered_levels: int
    flicker_n: int
    cascade: bool
    thin: bool
    book_trust: float | None
    tape_trust: float | None
    fingerprint: tuple[int, ...]
    evidence: dict[str, str]
    # False before the Passport churn norm is mature: scores are raw, not a veto.
    calibrated: bool = True
    churn_share: float = 0.0

    def __post_init__(self) -> None:
        if self.label not in SHADOW_LABELS:
            raise ValueError(f"unknown shadow label: {self.label!r}")
        for name in ("spoof_score", "opp_spoof_score", "layering_score"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        for name in ("book_trust", "tape_trust"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if len(self.fingerprint) != FINGERPRINT_LEN:
            raise ValueError("fingerprint length")

    @property
    def fingerprint_text(self) -> str:
        return "-".join(str(v) for v in self.fingerprint)


# Churn above the symbol's norm by this many robust σ is abnormal; below it the
# spoof/layering scores are damped to what exceeds the norm (a liquid book re-quotes
# constantly and that is not a trap).
CHURN_EXCESS_Z = 2.0
CHURN_DAMP_Z = 4.0


def churn_share(zone: SideScan, opp: SideScan) -> Decimal:
    """This window's vanished-without-print share across both sides, in [0, 1]."""
    added = zone.added_qty + opp.added_qty
    if added <= 0:
        return Decimal("0")
    vanished = zone.vanished_qty + opp.vanished_qty
    share = vanished / added
    return max(Decimal("0"), min(Decimal("1"), share))


def report(raw: RawWindow, frame: RetinaFrame, *, churn_z: Decimal | None = None) -> ShadowReport:
    """`churn_z`: this window's churn vs the Passport norm (robust z), None before the
    norm is mature. With a norm, spoof/layering scores are the EXCESS over normal
    churn; without one they are raw and `calibrated` is False — the eyelid then
    writes them but does not veto on them."""
    inside = [(ts, b) for ts, b in raw.book_path if raw.t0 < require_utc(ts) <= raw.t_end]
    prints = raw.prints()
    zone = _scan_side(raw, frame.depth_side_pre, raw.zone_side, inside, prints)
    opp = _scan_side(raw, frame.depth_opp_pre, raw.opp_side, inside, prints)

    spoof_zone = _spoof_score(zone, frame.depth_side_pre)
    spoof_opp = _spoof_score(opp, frame.depth_opp_pre)
    layering, layered_levels = _layering(zone, opp)
    calibrated = churn_z is not None
    if calibrated:
        z = float(churn_z)
        if z < CHURN_EXCESS_Z:
            # normal churn for this symbol: the window shows nothing beyond the norm
            damp = max(0.0, z) / CHURN_DAMP_Z
            spoof_zone = _clip(spoof_zone * damp)
            spoof_opp = _clip(spoof_opp * damp)
            layering = _clip(layering * damp)
            if layering < LAYER_LABEL:
                layered_levels = 0
    cascade = _cascade(frame)
    thin = frame.depth_side_rel is not None and frame.depth_side_rel < THIN_DEPTH_REL
    tape_trust = _tape_trust(raw, frame, prints)

    if not inside:
        label: ShadowLabel = "UNKNOWN"
        book_trust: float | None = None
    else:
        penalty = max(
            spoof_zone,
            layering,
            OPP_SPOOF_WEIGHT * spoof_opp,
            THIN_PENALTY if thin else 0.0,
            1.0 if cascade else 0.0,
        )
        book_trust = _clip(1.0 - penalty)
        if cascade:
            label = "CASCADE"
        elif layering >= LAYER_LABEL:
            label = "LAYERING"
        elif max(spoof_zone, spoof_opp) >= SPOOF_LABEL:
            label = "SPOOF"
        elif thin:
            label = "THIN"
        else:
            label = "CLEAN"

    spoof_side: Literal["zone", "opp"] | None = None
    if max(spoof_zone, spoof_opp) >= SPOOF_LABEL:
        spoof_side = "zone" if spoof_zone >= spoof_opp else "opp"

    fingerprint = _fingerprint(
        raw,
        frame,
        spoof_zone=spoof_zone,
        spoof_opp=spoof_opp,
        layering=layering,
        flicker_n=zone.flicker_n + opp.flicker_n,
        cascade=cascade,
        thin=thin,
    )
    evidence = {
        "zone_added": _dec(zone.added_qty),
        "zone_vanished": _dec(zone.vanished_qty),
        "zone_pulled": _dec(zone.pulled_qty),
        "zone_eaten": _dec(zone.eaten_qty),
        "opp_added": _dec(opp.added_qty),
        "opp_vanished": _dec(opp.vanished_qty),
        "depth_side_pre": _dec(frame.depth_side_pre),
        "n_prints": str(frame.n_prints),
        "books_in_window": str(len(inside)),
        "churn_share": _dec(churn_share(zone, opp)),
        "churn_z": None if churn_z is None else f"{float(churn_z):.2f}",
    }
    return ShadowReport(
        label=label,
        spoof_side=spoof_side,
        spoof_score=spoof_zone,
        opp_spoof_score=spoof_opp,
        layering_score=layering,
        layered_levels=layered_levels,
        flicker_n=zone.flicker_n + opp.flicker_n,
        cascade=cascade,
        thin=thin,
        book_trust=book_trust,
        tape_trust=tape_trust,
        fingerprint=fingerprint,
        evidence=evidence,
        calibrated=calibrated,
        churn_share=float(churn_share(zone, opp)),
    )


def _scan_side(
    raw: RawWindow,
    depth_pre: Decimal,
    side: str,
    inside: list[tuple[datetime, Book]],
    prints: list,
) -> SideScan:
    """Adds on one side inside the window: how much left without a print."""
    clf = TapeClassifier()
    hit_taker = "sell" if side == "bid" else "buy"
    end = inside[-1][1] if inside else raw.book_pre
    min_add = depth_pre * ADD_MIN_SHARE
    executed: dict[Decimal, list[tuple[datetime, Decimal]]] = defaultdict(list)
    for trade in prints:
        if clf.taker_side(trade) != hit_taker:
            continue
        executed[Decimal(str(trade.payload["px"]))].append(
            (require_utc(trade.exchange_ts), Decimal(str(trade.payload["qty"])))
        )
    added = Decimal("0")
    vanished = Decimal("0")
    levels_added: set[Decimal] = set()
    levels_vanished: set[Decimal] = set()
    flicker = 0
    for add in raw.adds:
        ts = require_utc(add.ts)
        if add.side != side or not (raw.t0 <= ts <= raw.t_end):
            continue
        if min_add > 0 and add.qty < min_add:
            continue
        before = _book_before(raw, inside, ts).level(side, str(add.px))
        end_level = end.level(side, str(add.px))
        gone = before + add.qty - end_level
        gone = min(max(gone, Decimal("0")), add.qty)
        printed = sum((q for t, q in executed.get(add.px, ()) if t > ts), Decimal("0"))
        silent = max(gone - printed, Decimal("0"))
        added += add.qty
        vanished += silent
        levels_added.add(add.px)
        if silent >= add.qty / 2:
            levels_vanished.add(add.px)
            life = _half_life(inside, side, add, before)
            if life is not None and life <= FLICKER_S:
                flicker += 1
    since = raw.t0 - timedelta(seconds=raw.window_s)
    pulled = Decimal("0")
    eaten = Decimal("0")
    for event in levels_in_window(raw.wall_events, since=since, until=raw.t_end):
        if event.side != side:
            continue
        if event.kind == "pulled":
            pulled += event.size
        elif event.kind == "eaten":
            eaten += event.size
    return SideScan(
        added_qty=added,
        vanished_qty=vanished,
        levels_added=len(levels_added),
        levels_vanished=len(levels_vanished),
        flicker_n=flicker,
        pulled_qty=pulled,
        eaten_qty=eaten,
    )


def _book_before(raw: RawWindow, inside: list[tuple[datetime, Book]], ts: datetime) -> Book:
    prior = [b for when, b in inside if require_utc(when) < ts]
    return prior[-1] if prior else raw.book_pre


def _half_life(
    inside: list[tuple[datetime, Book]], side: str, add: BookAdd, before: Decimal
) -> Decimal | None:
    """Seconds until the level lost half of the add. None if it never did in-window."""
    start = require_utc(add.ts)
    half = before + add.qty / 2
    for when, book in inside:
        ts = require_utc(when)
        if ts <= start:
            continue
        if book.level(side, str(add.px)) <= half:
            return Decimal(str((ts - start).total_seconds()))
    return None


def _spoof_score(scan: SideScan, depth_pre: Decimal) -> float:
    from_adds = 0.0
    if depth_pre > 0 and scan.added_qty >= depth_pre * SPOOF_MIN_ADD_SHARE:
        from_adds = scan.vanished_share
    from_walls = 0.0
    if depth_pre > 0 and scan.pulled_qty >= depth_pre * SPOOF_MIN_ADD_SHARE:
        total = scan.pulled_qty + scan.eaten_qty
        from_walls = float(scan.pulled_qty / total) if total > 0 else 0.0
    return _clip(max(from_adds, from_walls))


def _layering(zone: SideScan, opp: SideScan) -> tuple[float, int]:
    best = 0.0
    levels = 0
    for scan in (zone, opp):
        if scan.levels_vanished < LAYER_MIN_LEVELS or scan.levels_added == 0:
            continue
        share = scan.vanished_share
        if share < LAYER_SHARE:
            continue
        score = (scan.levels_vanished / scan.levels_added) * share
        if score > best:
            best = _clip(score)
            levels = scan.levels_vanished
    return best, levels


def _cascade(frame: RetinaFrame) -> bool:
    if frame.n_prints < CASCADE_MIN_PRINTS:
        return False
    if frame.rate_rel is None or frame.range_rel is None:
        return False
    if frame.aggression is None or frame.depth_end_ratio is None:
        return False
    return (
        frame.rate_rel >= CASCADE_RATE_REL
        and abs(frame.aggression) >= CASCADE_AGGRESSION
        and frame.depth_end_ratio <= CASCADE_DEPTH_RATIO
        and frame.range_rel >= CASCADE_RANGE_REL
    )


def _tape_trust(raw: RawWindow, frame: RetinaFrame, prints: list) -> float | None:
    if len(prints) < TAPE_MIN_PRINTS:
        return None
    pairs = Counter(
        (_dec(Decimal(str(t.payload["px"]))), _dec(Decimal(str(t.payload["qty"])))) for t in prints
    )
    dup_share = 1.0 - len(pairs) / len(prints)
    excess = max(0.0, dup_share - DUP_NORMAL_SHARE)
    trust = _clip(1.0 - 2.0 * excess)
    if (
        frame.ofi_rel is not None
        and frame.mid_move_ticks is not None
        and abs(frame.ofi_rel) >= OFI_REL_MIN
        and abs(frame.mid_move_ticks) >= MID_MOVE_MIN_TICKS
        and (frame.ofi_rel > 0) != (frame.mid_move_ticks > 0)
    ):
        trust = min(trust, OFI_MISMATCH_TRUST)
    return trust


def _fingerprint(
    raw: RawWindow,
    frame: RetinaFrame,
    *,
    spoof_zone: float,
    spoof_opp: float,
    layering: float,
    flicker_n: int,
    cascade: bool,
    thin: bool,
) -> tuple[int, ...]:
    return (
        0 if raw.zone.side == "support" else 1,
        _q4(spoof_zone),
        _q4(spoof_opp),
        _q4(layering),
        _bucket_aggression(frame.aggression),
        _bucket_ratio(frame.depth_end_ratio),
        _bucket_rate(frame.rate_rel),
        min(flicker_n, 3),
        1 if cascade else 0,
        1 if thin else 0,
    )


def _q4(x: float) -> int:
    return min(3, max(0, int(x * 4)))


def _bucket_aggression(a: Decimal | None) -> int:
    if a is None:
        return 4
    return min(3, max(0, int((a + 1) / 2 * 4)))


def _bucket_ratio(r: Decimal | None) -> int:
    if r is None:
        return 4
    if r < Decimal("0.4"):
        return 0
    if r < Decimal("0.8"):
        return 1
    if r < Decimal("1.2"):
        return 2
    return 3


def _bucket_rate(r: Decimal | None) -> int:
    if r is None:
        return 4
    if r < Decimal("0.5"):
        return 0
    if r < 2:
        return 1
    if r < 4:
        return 2
    return 3


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def _dec(x: Decimal) -> str:
    return format(x.normalize(), "f")
