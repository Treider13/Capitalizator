"""Calibration from paper results (D-03, §5.7): data decides whether a class has edge.

`n_cav >= 20` in the jury is a frequency count — it says a label happened 20
times, not that it predicted anything. This module reads closed, filled shadow
paper trades grouped by (idea, CAV, ZLG) and asks one question per class: does
it make money net of costs?

Refutation (audit B6): the statistic is the *mean net R* with a one-sided upper
confidence bound (mean + z·s/√n). A class is refuted when n ≥ mature_n and even
that optimistic bound is ≤ 0. The old rule compared the share of `r_net > 0`
(which counts a +0.3R trail exit as a win) with a break-even winrate written
for a 2R target, and double-counted fees — a class could pass while losing money.
The Wilson interval of the winrate is kept for display.

Refuted classes are not sent live; they keep trading on paper, so the verdict can
flip when the data changes. No class is ever promoted here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from capitalizator.stats import Z95, mature_n, wilson_interval

MIN_N = mature_n()  # below this the interval is too wide to refute anything


@dataclass(frozen=True)
class ClassStat:
    key: str
    n: int
    wins: int
    winrate: Decimal | None
    lower: Decimal | None
    upper: Decimal | None
    avg_r_net: Decimal | None
    sd_r_net: Decimal | None = None
    # one-sided 95% upper bound of the mean net R: mean + z·s/√n
    upper_r_net: Decimal | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "n": self.n,
            "wins": self.wins,
            "winrate": None if self.winrate is None else str(self.winrate),
            "lower": None if self.lower is None else str(self.lower),
            "upper": None if self.upper is None else str(self.upper),
            "avg_r_net": None if self.avg_r_net is None else str(self.avg_r_net),
            "sd_r_net": None if self.sd_r_net is None else str(self.sd_r_net),
            "upper_r_net": None if self.upper_r_net is None else str(self.upper_r_net),
        }


def wilson(wins: int, n: int, *, z: Decimal = Z95) -> tuple[Decimal, Decimal]:
    return wilson_interval(wins, n, z=z)


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
        mean = sum(rs, Decimal(0)) / Decimal(n)
        sd: Decimal | None = None
        upper_mean: Decimal | None = None
        if n >= 2:
            var = sum(((r - mean) ** 2 for r in rs), Decimal(0)) / Decimal(n - 1)
            sd = var.sqrt()
            upper_mean = mean + Z95 * sd / Decimal(n).sqrt()
        out[key] = ClassStat(
            key=key,
            n=n,
            wins=wins,
            winrate=Decimal(wins) / Decimal(n),
            lower=lo,
            upper=hi,
            avg_r_net=mean,
            sd_r_net=sd,
            upper_r_net=upper_mean,
        )
    return out


def refuted(
    stat: ClassStat | None, *, breakeven: Decimal | None = None, min_n: int | None = None
) -> bool:
    """True only when there is enough data AND even the optimistic bound of the mean
    net R is ≤ 0. `breakeven` is accepted for callers that still pass it; the verdict
    no longer depends on a winrate target."""
    limit = MIN_N if min_n is None else min_n
    if stat is None or stat.n < limit or stat.upper_r_net is None:
        return False
    return stat.upper_r_net <= 0


def to_meta(stats: Mapping[str, ClassStat]) -> str:
    return json.dumps({k: v.to_payload() for k, v in sorted(stats.items())}, sort_keys=True)
