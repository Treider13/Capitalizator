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
   A stop landing within max(cluster_ticks · tick, 0.1 · ATR) of a round level
   or another zone edge is pushed to the far side of it. Size is then recomputed
   from the wider stop — never the other way round.

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

MODES = frozenset({"structural", "volatility", "hybrid", "manual_bounded"})
K_ATR_DEFAULT = Decimal("0.5")  # provenance: docs 0.5–0.7 ATR; status paper until calibrated
CLUSTER_TICKS_DEFAULT = 5  # provenance: prs_delta_ticks (registry.yaml) — the "near" band
CLUSTER_ATR_DEFAULT = Decimal("0.1")  # 0.1 ATR; 5 ticks alone is cosmetic on BTC
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


def cluster_band(
    *,
    tick: Decimal,
    atr: Decimal | None,
    cluster_ticks: int = CLUSTER_TICKS_DEFAULT,
) -> Decimal:
    """Magnet proximity: max(cluster_ticks · tick, 0.1 · ATR). ATR None → ticks only."""
    if tick <= 0:
        raise ValueError("tick must be > 0")
    band = tick * cluster_ticks
    if atr is not None and atr > 0:
        band = max(band, CLUSTER_ATR_DEFAULT * atr)
    return (band / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def push_past_clusters(
    *,
    side: str,
    stop: Decimal,
    tick: Decimal,
    atr: Decimal | None = None,
    zones: Sequence[Zone] = (),
    liq_levels: Sequence[Decimal] = (),
    cluster_ticks: int = CLUSTER_TICKS_DEFAULT,
) -> tuple[Decimal, bool, Decimal | None]:
    """One push past the farthest magnet (round / zone edge / liq) inside the band.

    Returns (stop, moved, magnet). Never walks: measured from the incoming stop.
    """
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy|sell")
    if tick <= 0 or stop <= 0:
        raise ValueError("tick/stop must be > 0")
    band = cluster_band(tick=tick, atr=atr, cluster_ticks=cluster_ticks)
    magnets: list[Decimal] = list(round_levels_near(stop, span=band, tick=tick))
    for z in zones:
        magnets.extend((z.lo, z.hi))
    magnets.extend(lvl for lvl in liq_levels if lvl > 0 and abs(lvl - stop) <= band)
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
    if best is None:
        return stop, False, None
    out = (best / tick).to_integral_value(
        rounding=ROUND_FLOOR if side == "buy" else ROUND_CEILING
    ) * tick
    return out, True, best_level


def widen_past_value_area(
    *,
    side: str,
    stop: Decimal,
    tick: Decimal,
    vah: Decimal | None,
    val: Decimal | None,
) -> tuple[Decimal, bool, Decimal | None]:
    """Push the stop past VAL (long) / VAH (short) when that is farther from entry.

    A value-area edge on the entry side is ignored. This never tightens.
    """
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy|sell")
    if tick <= 0 or stop <= 0:
        raise ValueError("tick/stop must be > 0")
    levels: list[Decimal] = []
    if side == "buy":
        if val is not None and val > 0:
            levels.append(val)
        if vah is not None and vah > 0 and vah < stop:
            levels.append(vah)
    else:
        if vah is not None and vah > 0:
            levels.append(vah)
        if val is not None and val > 0 and val > stop:
            levels.append(val)
    best = stop
    used: Decimal | None = None
    for level in levels:
        pushed = level - tick if side == "buy" else level + tick
        if (side == "buy" and pushed < best) or (side == "sell" and pushed > best):
            best, used = pushed, level
    if used is None:
        return stop, False, None
    out = (best / tick).to_integral_value(
        rounding=ROUND_FLOOR if side == "buy" else ROUND_CEILING
    ) * tick
    return out, True, used


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
    manual_frac: Decimal | None = None,
    max_stop_pct: Decimal | None = None,
    vah: Decimal | None = None,
    val: Decimal | None = None,
) -> StopDecision:
    """Widen the structural stop by a volatility buffer and push it past clusters.

    mode: structural (no buffer, no push) | volatility (buffer only) | hybrid (all) |
    manual_bounded (operator distance `manual_frac` × entry, bounded: never tighter
    than the hybrid stop, never farther than `max_stop_atr`; clusters still avoided).
    The result is never tighter than `structural`.

    `k_atr` is the window's buffer (sessions.yaml, widened by calibration).
    `liq_levels` are liquidation clusters from the allLiquidation feed: magnets like
    round numbers and zone edges (retail stops sit where leverage was flushed).
    `max_stop_atr` with `entry`: the finished stop may not sit farther than this many
    ATR from the entry — a setup whose invalidation is that far away is refused
    (ValueError), it is not "fitted" by shrinking the buffer. Size follows the stop,
    never the other way round.
    `max_stop_pct` with `entry`: the same refusal in price-percent terms (Э1).
    Without `entry` the percent ceiling cannot be measured and is not applied.
    """
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy|sell")
    if tick <= 0 or structural <= 0:
        raise ValueError("tick/structural must be > 0")
    if k_atr <= 0:
        raise ValueError("k_atr must be > 0")
    if max_stop_atr is not None and max_stop_atr <= 0:
        raise ValueError("max_stop_atr must be > 0")
    if max_stop_pct is not None and max_stop_pct <= 0:
        raise ValueError("max_stop_pct must be > 0")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    comps: dict[str, str] = {"structural": str(structural), "mode": mode}
    if mode == "manual_bounded":
        if manual_frac is None or manual_frac <= 0:
            raise ValueError("manual_bounded needs manual_frac > 0")
        if entry is None or entry <= 0:
            raise ValueError("manual_bounded needs the entry price")
        # The automatic hybrid stop is the floor: an operator distance inside the
        # structure + buffer is not a stop, it is a donation to the sweep.
        auto = initial_stop(
            side=side, structural=structural, tick=tick, atr=atr, spread=spread, zones=zones,
            k_atr=k_atr, cluster_ticks=cluster_ticks, spread_mult=spread_mult, mode="hybrid",
            liq_levels=liq_levels, max_stop_atr=None, entry=entry,
            vah=vah, val=val,
        )
        dist = (entry * manual_frac / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        manual = entry - dist if side == "buy" else entry + dist
        stop = min(manual, auto.stop) if side == "buy" else max(manual, auto.stop)
        comps.update(auto.components)
        comps["mode"] = mode
        comps["manual_frac"] = str(manual_frac)
        comps["manual_stop"] = str(manual)
        comps["bounded_by_auto"] = str(stop == auto.stop and stop != manual)
        if max_stop_atr is not None and atr is not None and atr > 0:
            dist_atr = abs(entry - stop) / atr
            comps["stop_atr"] = str(dist_atr)
            comps["max_stop_atr"] = str(max_stop_atr)
            if dist_atr > max_stop_atr:
                raise ValueError(
                    f"stop_too_wide: {dist_atr} ATR from entry > max {max_stop_atr} ATR"
                )
        _enforce_max_stop_pct(stop=stop, entry=entry, max_stop_pct=max_stop_pct, comps=comps)
        return StopDecision(
            stop=stop,
            structural=structural,
            buffer=abs(stop - structural),
            moved_for_cluster=auto.moved_for_cluster,
            components=comps,
        )
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
        band = cluster_band(tick=tick, atr=atr, cluster_ticks=cluster_ticks)
        liq_near = [lvl for lvl in liq_levels if lvl > 0 and abs(lvl - stop) <= band]
        if liq_near:
            comps["liq_levels_near"] = str(len(liq_near))
        stop, moved, cluster_level = push_past_clusters(
            side=side,
            stop=stop,
            tick=tick,
            atr=atr,
            zones=zones,
            liq_levels=liq_levels,
            cluster_ticks=cluster_ticks,
        )
        if moved and cluster_level is not None:
            comps["cluster_level"] = format(_plain(cluster_level), "f")
    if mode in {"volatility", "hybrid"}:
        stop, va_moved, va_level = widen_past_value_area(
            side=side, stop=stop, tick=tick, vah=vah, val=val
        )
        if va_moved and va_level is not None:
            comps["value_area"] = format(_plain(va_level), "f")
            moved = moved or va_moved
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
    _enforce_max_stop_pct(stop=stop, entry=entry, max_stop_pct=max_stop_pct, comps=comps)
    return StopDecision(
        stop=stop,
        structural=structural,
        buffer=buffer,
        moved_for_cluster=moved,
        components=comps,
    )


def _enforce_max_stop_pct(
    *,
    stop: Decimal,
    entry: Decimal | None,
    max_stop_pct: Decimal | None,
    comps: dict[str, str],
) -> None:
    """Refuse — do not shrink — when the finished stop is farther than the operator %.

    Missing entry: the ceiling cannot be measured (never a guessed price).
    """
    if max_stop_pct is None or entry is None or entry <= 0:
        return
    frac = abs(entry - stop) / entry
    comps["stop_pct"] = str(frac)
    comps["max_stop_pct"] = str(max_stop_pct)
    if frac > max_stop_pct:
        raise ValueError(f"stop_too_wide_pct: {frac} of entry > max {max_stop_pct}")


def soft_exit(*, side: str, structural: Decimal, bar: Bar) -> bool:
    """Closed working bar beyond the structural level → thesis dead before the hard stop."""
    if side == "buy":
        return bar.close < structural
    return bar.close > structural
