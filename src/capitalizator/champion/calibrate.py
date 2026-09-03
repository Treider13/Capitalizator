"""Calibration from paper results (D-03, §5.7): data decides whether a class has edge.

`n_cav >= 20` in the jury is a frequency count — it says a label happened 20
times, not that it predicted anything. This module reads closed, filled shadow
paper trades grouped by class and computes the Wilson 95% interval of the net
winrate. A class is *refuted* when the interval's UPPER bound is below the
break-even winrate the EV gate already computes for a 2R target
((R + costs) / 3R). Refuted classes are not sent live; they keep trading on
paper, so the verdict can flip when the data changes.

Class dimensions (sessions release): `idea | CAV | ZLG | window | symbol_group`.
Two views are kept — the full key and the window aggregate (`idea|cav|zlg|window|*`) —
so a window can be refuted on 30 trades before every symbol group reaches 30.
The window aggregate also drives `eligible()`: a window the operator has closed in
`sessions.yaml` whose paper LOWER bound clears break-even on ≥ 40 trades is flagged
for a human to open. Nothing here opens anything by itself.

`k_atr_by_window` re-estimates the stop buffer from the MAE of *winning* paper trades
(90th percentile of MAE/ATR, n ≥ 30): the buffer that would have kept nine winners
in ten alive. The desk takes max(configured, calibrated) — the calibrator widens,
never narrows.

Wilson (1927) is used instead of a normal approximation because n is small.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

MIN_N = 30  # below this the interval is too wide to refute anything
ELIGIBLE_MIN_N = 40  # below this a closed window cannot ask to be opened
K_ATR_MIN_N = 30
K_ATR_PERCENTILE = Decimal("0.9")
Z95 = Decimal("1.959964")
ANY = "*"


@dataclass(frozen=True)
class ClassStat:
    key: str
    n: int
    wins: int
    winrate: Decimal | None
    lower: Decimal | None
    upper: Decimal | None
    avg_r_net: Decimal | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "n": self.n,
            "wins": self.wins,
            "winrate": None if self.winrate is None else str(self.winrate),
            "lower": None if self.lower is None else str(self.lower),
            "upper": None if self.upper is None else str(self.upper),
            "avg_r_net": None if self.avg_r_net is None else str(self.avg_r_net),
        }


def wilson(wins: int, n: int, *, z: Decimal = Z95) -> tuple[Decimal, Decimal]:
    if n <= 0:
        raise ValueError("n must be > 0")
    p = Decimal(wins) / Decimal(n)
    nn = Decimal(n)
    denom = 1 + z * z / nn
    centre = (p + z * z / (2 * nn)) / denom
    half = z * ((p * (1 - p) / nn + z * z / (4 * nn * nn)) ** Decimal("0.5")) / denom
    return max(Decimal(0), centre - half), min(Decimal(1), centre + half)


def class_key(
    *,
    idea: str | None,
    cav: str | None,
    zlg: str | None,
    window: str | None = None,
    group: str | None = None,
) -> str:
    """Full key. `window`/`group` None → `*` (the aggregate over that dimension)."""
    return "|".join((idea or "-", cav or "-", zlg or "-", window or ANY, group or ANY))


def window_key(key: str) -> str:
    """`idea|cav|zlg|window|group` → `idea|cav|zlg|window|*`."""
    parts = key.split("|")
    if len(parts) != 5:
        raise ValueError(f"not a class key: {key!r}")
    return "|".join((*parts[:4], ANY))


def legacy_key(key: str) -> str:
    """`idea|cav|zlg|window|group` → `idea|cav|zlg|*|*` (pre-sessions class)."""
    parts = key.split("|")
    if len(parts) != 5:
        raise ValueError(f"not a class key: {key!r}")
    return "|".join((*parts[:3], ANY, ANY))


def _row_key(row: Mapping[str, Any]) -> str:
    labels = row.get("labels") if isinstance(row.get("labels"), Mapping) else {}
    return class_key(
        idea=row.get("tag"),
        cav=labels.get("cav_label"),
        zlg=labels.get("zlg_label"),
        window=labels.get("window"),
        group=labels.get("symbol_group"),
    )


def _filled_closed(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, Decimal, Mapping]]:
    out: list[tuple[str, Decimal, Mapping]] = []
    for row in rows:
        if row.get("entry_px") in (None, "") or row.get("r_net") in (None, ""):
            continue
        try:
            r = Decimal(str(row["r_net"]))
        except ArithmeticError:
            continue
        out.append((_row_key(row), r, row))
    return out


def _stat(key: str, rs: list[Decimal]) -> ClassStat:
    n = len(rs)
    wins = sum(1 for r in rs if r > 0)
    lo, hi = wilson(wins, n)
    return ClassStat(
        key=key,
        n=n,
        wins=wins,
        winrate=Decimal(wins) / Decimal(n),
        lower=lo,
        upper=hi,
        avg_r_net=sum(rs, Decimal(0)) / Decimal(n),
    )


def class_stats(rows: Iterable[Mapping[str, Any]]) -> dict[str, ClassStat]:
    """Filled, closed paper rows → per-class stats at three granularities.

    Full key, window aggregate (`...|window|*`) and legacy aggregate (`...|*|*`).
    Unfilled rows are not evidence. Rows without a window label (pre-sessions
    journal) only feed the legacy aggregate.
    """
    buckets: dict[str, list[Decimal]] = {}
    for key, r, _row in _filled_closed(rows):
        buckets.setdefault(legacy_key(key), []).append(r)
        parts = key.split("|")
        if parts[3] != ANY:
            buckets.setdefault(window_key(key), []).append(r)
            if parts[4] != ANY:
                buckets.setdefault(key, []).append(r)
    return {key: _stat(key, rs) for key, rs in buckets.items()}


def lookup(stats: Mapping[str, ClassStat], key: str) -> ClassStat | None:
    """Most specific stat that reached MIN_N: full → window → legacy. Else the fullest seen."""
    chain = (key, window_key(key), legacy_key(key))
    for k in chain:
        stat = stats.get(k)
        if stat is not None and stat.n >= MIN_N:
            return stat
    for k in chain:
        stat = stats.get(k)
        if stat is not None:
            return stat
    return None


def refuted(stat: ClassStat | None, *, breakeven: Decimal, min_n: int = MIN_N) -> bool:
    """True only when there is enough data AND even the optimistic bound loses money."""
    if stat is None or stat.n < min_n or stat.upper is None:
        return False
    return stat.upper < breakeven


def eligible(stat: ClassStat | None, *, breakeven: Decimal, min_n: int = ELIGIBLE_MIN_N) -> bool:
    """True when even the pessimistic bound beats break-even on enough trades.

    Used for windows the operator closed in sessions.yaml: the desk flags them,
    a human opens them. Never called for size.
    """
    if stat is None or stat.n < min_n or stat.lower is None:
        return False
    return stat.lower > breakeven


def eligible_windows(
    stats: Mapping[str, ClassStat], *, breakeven: Decimal, closed_windows: Iterable[str]
) -> dict[str, list[str]]:
    """window → window-aggregate class keys whose lower bound clears break-even."""
    closed = set(closed_windows)
    out: dict[str, list[str]] = {}
    for key, stat in stats.items():
        parts = key.split("|")
        if parts[3] not in closed or parts[4] != ANY:
            continue
        if eligible(stat, breakeven=breakeven):
            out.setdefault(parts[3], []).append(key)
    return {w: sorted(v) for w, v in sorted(out.items())}


def k_atr_by_window(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_n: int = K_ATR_MIN_N,
    percentile: Decimal = K_ATR_PERCENTILE,
) -> dict[str, Decimal]:
    """window → 90th percentile of MAE/ATR over *winning* filled trades (n ≥ min_n).

    MAE is the worst price against the entry; in ATR units it is the buffer a stop
    needed to survive that winner. Rows without `labels.atr` or `mae_px` are skipped.
    """
    samples: dict[str, list[Decimal]] = {}
    for _key, r, row in _filled_closed(rows):
        if r <= 0:
            continue
        labels = row.get("labels") if isinstance(row.get("labels"), Mapping) else {}
        window = labels.get("window")
        atr_raw = labels.get("atr")
        if not window or atr_raw in (None, ""):
            continue
        try:
            atr = Decimal(str(atr_raw))
            entry = Decimal(str(row["entry_px"]))
            mae_px = Decimal(str(row["mae_px"]))
        except (KeyError, ArithmeticError, TypeError):
            continue
        if atr <= 0:
            continue
        samples.setdefault(str(window), []).append(abs(entry - mae_px) / atr)
    out: dict[str, Decimal] = {}
    for window, xs in samples.items():
        if len(xs) < min_n:
            continue
        ordered = sorted(xs)
        idx = int((percentile * (len(ordered) - 1)).to_integral_value(rounding="ROUND_CEILING"))
        out[window] = ordered[min(len(ordered) - 1, max(0, idx))]
    return out


def loss_series_by_window(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[int]]:
    """window → chronological 0/1 series (1 = the filled trade lost) for drift detection."""
    dated: dict[str, list[tuple[str, int]]] = {}
    for _key, r, row in _filled_closed(rows):
        labels = row.get("labels") if isinstance(row.get("labels"), Mapping) else {}
        window = labels.get("window")
        if not window:
            continue
        stamp = str(row.get("closed_at") or row.get("filled_at") or "")
        dated.setdefault(str(window), []).append((stamp, 1 if r <= 0 else 0))
    return {w: [bit for _s, bit in sorted(xs)] for w, xs in dated.items()}


def median_hold_hours(
    rows: Iterable[Mapping[str, Any]], *, min_n: int = MIN_N
) -> dict[str, Decimal]:
    """`idea|window` → median hold in hours over filled trades (n ≥ min_n).

    Feeds the EV gate's expected funding: a class that holds six hours crosses more
    settlements than the two-hour default assumes.
    """
    samples: dict[str, list[Decimal]] = {}
    for key, _r, row in _filled_closed(rows):
        hold = row.get("hold_s")
        if hold in (None, ""):
            continue
        try:
            hours = Decimal(str(hold)) / Decimal(3600)
        except ArithmeticError:
            continue
        if hours <= 0:
            continue
        parts = key.split("|")
        if parts[3] == ANY:
            continue
        samples.setdefault(f"{parts[0]}|{parts[3]}", []).append(hours)
    out: dict[str, Decimal] = {}
    for k, xs in samples.items():
        if len(xs) < min_n:
            continue
        ordered = sorted(xs)
        mid = len(ordered) // 2
        out[k] = (
            ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        )
    return out


def to_meta(stats: Mapping[str, ClassStat]) -> str:
    return json.dumps({k: v.to_payload() for k, v in sorted(stats.items())}, sort_keys=True)
