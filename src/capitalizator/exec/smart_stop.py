"""Stop placement that is not "8 ticks behind the band" (§6 of the plan).

Three layers, every one with a source:

1. Structural: behind the level the market rejected — the spring wick or the
   zone edge (`strategy_bounce.stop_behind[_wick]`).
2. Volatility buffer: k·ATR of the working TF. The desk documents 0.5–0.7 ATR
   (IMPLEMENTATION.md §3 "Стоп за зоной ~0.5–0.7 ATR", TRAIL-RUNNERS.md). k
   starts at 0.5 with provenance `paper`; `champion/calibrate.py` re-estimates it
   from the MAE distribution of winning paper trades once n is large enough.
3. Cluster avoidance: stops parked exactly at round numbers get run (Osler 2005,
   "Stop-loss orders and price cascades in currency markets", J. Int. Money &
   Finance: stop-loss clustering at round numbers, cascades when they trigger).
   A stop landing within `cluster_ticks` of a round level or another zone edge is
   pushed to the far side of it. Size is then recomputed from the wider stop —
   never the other way round.

`soft_exit` is the confirmation exit: a closed working bar beyond the structural
level while the hard stop (with buffer) is still alive → leave at market instead
of waiting to be swept. Recorded as `exit_reason="soft"` on paper so data can
compare soft vs hard.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from capitalizator.zones.model import Bar, Zone

K_ATR_DEFAULT = Decimal("0.5")  # provenance: docs 0.5–0.7 ATR; status paper until calibrated
CLUSTER_TICKS_DEFAULT = 5  # provenance: prs_delta_ticks (registry.yaml) — the "near" band
SPREAD_MULT_DEFAULT = Decimal("3")


@dataclass(frozen=True)
class StopDecision:
    stop: Decimal
    structural: Decimal
    buffer: Decimal
    moved_for_cluster: bool
    components: dict[str, str] = field(default_factory=dict)


def round_step(px: Decimal, *, tick: Decimal | None = None) -> Decimal:
    """Round-number grid one decade below the price magnitude: 65 000 → 1 000,
    100.4 → 10, 99.9 → 1, 0.53 → 0.01. Never finer than 10 ticks."""
    if px <= 0:
        raise ValueError("px must be > 0")
    magnitude = px.adjusted()  # floor(log10(px))
    step = Decimal(1).scaleb(magnitude - 1)
    if tick is not None and tick > 0:
        step = max(step, tick * 10)
    return step


def round_levels_near(
    px: Decimal, *, span: Decimal, tick: Decimal | None = None
) -> list[Decimal]:
    """Round numbers within ±span of px on the `round_step` grid."""
    step = round_step(px, tick=tick)
    lo = ((px - span) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    hi = ((px + span) / step).to_integral_value(rounding=ROUND_CEILING) * step
    out: list[Decimal] = []
    level = lo
    while level <= hi:
        out.append(_plain(level))
        level += step
    return out


def _plain(value: Decimal) -> Decimal:
    """1.0E+2 → 100; 0.50 → 0.5. Keeps journal strings readable and comparable."""
    if value == value.to_integral_value():
        return value.quantize(Decimal(1))
    return value.normalize()


def initial_stop(
    *,
    side: str,
    structural: Decimal,
    tick: Decimal,
    atr: Decimal | None,
    spread: Decimal | None,
    zones: Sequence[Zone] = (),
    k_atr: Decimal = K_ATR_DEFAULT,
    cluster_ticks: int = CLUSTER_TICKS_DEFAULT,
    spread_mult: Decimal = SPREAD_MULT_DEFAULT,
    mode: str = "hybrid",
    liq_levels: Sequence[Decimal] = (),
    max_stop_atr: Decimal | None = None,
    entry: Decimal | None = None,
) -> StopDecision:
    """Widen the structural stop by a volatility buffer and push it past clusters.

    mode: structural (no buffer, no push) | volatility (buffer only) | hybrid (all).
    The result is never tighter than `structural`.

    `k_atr` is the window's buffer (sessions.yaml, widened by calibration).
    `liq_levels` are liquidation clusters from the allLiquidation feed: magnets like
    round numbers and zone edges (retail stops sit where leverage was flushed).
    `max_stop_atr` with `entry`: the finished stop may not sit farther than this many
    ATR from the entry — a setup whose invalidation is that far away is refused
    (ValueError), it is not "fitted" by shrinking the buffer. Size follows the stop,
    never the other way round.
    """
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy|sell")
    if tick <= 0 or structural <= 0:
        raise ValueError("tick/structural must be > 0")
    if k_atr <= 0:
        raise ValueError("k_atr must be > 0")
    if max_stop_atr is not None and max_stop_atr <= 0:
        raise ValueError("max_stop_atr must be > 0")
    comps: dict[str, str] = {"structural": str(structural), "mode": mode}
    buffer = Decimal("0")
    if mode in {"volatility", "hybrid"}:
        candidates = [tick]
        comps["k_atr"] = str(k_atr)
        if atr is not None and atr > 0:
            candidates.append(k_atr * atr)
            comps["atr"] = str(atr)
        if spread is not None and spread > 0:
            candidates.append(spread * spread_mult)
            comps["spread"] = str(spread)
        buffer = max(candidates)
        buffer = (buffer / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    stop = structural - buffer if side == "buy" else structural + buffer
    moved = False
    if mode == "hybrid":
        band = tick * cluster_ticks
        magnets: list[Decimal] = list(round_levels_near(stop, span=band, tick=tick))
        for z in zones:
            magnets.extend((z.lo, z.hi))
        liq_near = [lvl for lvl in liq_levels if lvl > 0 and abs(lvl - stop) <= band]
        if liq_near:
            magnets.extend(liq_near)
            comps["liq_levels_near"] = str(len(liq_near))
        # One push, measured from the buffered stop: past the farthest magnet inside
        # the band. Chaining pushes off the moved stop would walk away indefinitely.
        base = stop
        best: Decimal | None = None
        best_level: Decimal | None = None
        for level in magnets:
            if abs(level - base) > band:
                continue
            pushed = level - band if side == "buy" else level + band
            if (side == "buy" and pushed < base) or (side == "sell" and pushed > base):
                if best is None or (pushed < best if side == "buy" else pushed > best):
                    best, best_level = pushed, level
        if best is not None:
            stop = (best / tick).to_integral_value(
                rounding=ROUND_FLOOR if side == "buy" else ROUND_CEILING
            ) * tick
            moved = True
            comps["cluster_level"] = format(_plain(best_level or Decimal(0)), "f")
    if stop <= 0:
        raise ValueError("stop would be <= 0")
    comps["buffer"] = str(buffer)
    if max_stop_atr is not None and entry is not None and atr is not None and atr > 0:
        dist_atr = abs(entry - stop) / atr
        comps["stop_atr"] = str(dist_atr)
        comps["max_stop_atr"] = str(max_stop_atr)
        if dist_atr > max_stop_atr:
            raise ValueError(
                f"stop_too_wide: {dist_atr} ATR from entry > max {max_stop_atr} ATR"
            )
    return StopDecision(
        stop=stop,
        structural=structural,
        buffer=buffer,
        moved_for_cluster=moved,
        components=comps,
    )


def soft_exit(*, side: str, structural: Decimal, bar: Bar) -> bool:
    """Closed working bar beyond the structural level → thesis dead before the hard stop."""
    if side == "buy":
        return bar.close < structural
    return bar.close > structural
