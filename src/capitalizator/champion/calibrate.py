"""Calibration from paper results (D-03, §5.7): data decides whether a class has edge.

`n_cav >= 20` in the jury is a frequency count — it says a label happened 20
times, not that it predicted anything. This module reads closed, filled shadow
paper trades grouped by (idea, CAV, ZLG) and computes the Wilson 95% interval of
the net winrate. A class is *refuted* when the interval's UPPER bound is below
the break-even winrate the EV gate already computes for a 2R target
((R + costs) / 3R). Refuted classes are not sent live; they keep trading on
paper, so the verdict can flip when the data changes.

Wilson (1927) is used instead of a normal approximation because n is small.
No class is ever promoted here — only refuted or "not enough data".
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

MIN_N = 30  # below this the interval is too wide to refute anything
Z95 = Decimal("1.959964")


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


def class_key(*, idea: str | None, cav: str | None, zlg: str | None) -> str:
    return f"{idea or '-'}|{cav or '-'}|{zlg or '-'}"


def class_stats(rows: Iterable[Mapping[str, Any]]) -> dict[str, ClassStat]:
    """Filled, closed paper rows → per-class stats. Unfilled rows are not evidence."""
    buckets: dict[str, list[Decimal]] = {}
    for row in rows:
        if row.get("entry_px") in (None, "") or row.get("r_net") in (None, ""):
            continue
        labels = row.get("labels") if isinstance(row.get("labels"), Mapping) else {}
        key = class_key(
            idea=row.get("tag"), cav=labels.get("cav_label"), zlg=labels.get("zlg_label")
        )
        try:
            buckets.setdefault(key, []).append(Decimal(str(row["r_net"])))
        except ArithmeticError:
            continue
    out: dict[str, ClassStat] = {}
    for key, rs in buckets.items():
        n = len(rs)
        wins = sum(1 for r in rs if r > 0)
        lo, hi = wilson(wins, n)
        out[key] = ClassStat(
            key=key,
            n=n,
            wins=wins,
            winrate=Decimal(wins) / Decimal(n),
            lower=lo,
            upper=hi,
            avg_r_net=sum(rs, Decimal(0)) / Decimal(n),
        )
    return out


def refuted(stat: ClassStat | None, *, breakeven: Decimal, min_n: int = MIN_N) -> bool:
    """True only when there is enough data AND even the optimistic bound loses money."""
    if stat is None or stat.n < min_n or stat.upper is None:
        return False
    return stat.upper < breakeven


def to_meta(stats: Mapping[str, ClassStat]) -> str:
    return json.dumps({k: v.to_payload() for k, v in sorted(stats.items())}, sort_keys=True)
