"""Exam: champion vs challenger on their own paper results. Contour C, §6.1 (6).

The champion trades the desk's law (paper source `shadow`, and `demo` when a key
is on). Challengers trade the same touches on paper with another reading
(source `challenger` / `fade`). Every 15–20 days — or when an operator asks — the
exam compares them on *closed, filled* paper trades:

  pass ⇔ n_challenger ≥ n_min
       ∧ expectancy_challenger (mean net R) > expectancy_champion
       ∧ the one-sided lower bound of the challenger's mean net R > 0
       ∧ max drawdown (in R) of the challenger ≤ that of the champion
       ∧ both series carry fees + funding (paper does; `r_net` is net)

Nothing is promoted automatically. `promote()` returns a report; the desk records
it and flips the champion label only when `passed` is True *and* the operator
acknowledged — a data-backed switch of a label, never a code rewrite in the fight.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalizator.stats import Z95, mature_n

CHAMPION_SOURCES = frozenset({"shadow", "demo"})
CHALLENGER_SOURCES = frozenset({"challenger", "fade"})


@dataclass(frozen=True)
class Series:
    role: str
    n: int
    mean_r: Decimal | None
    sd_r: Decimal | None
    lower_r: Decimal | None  # one-sided 95% lower bound of the mean
    max_dd_r: Decimal | None  # deepest peak-to-trough of cumulative net R
    sum_r: Decimal | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "n": self.n,
            "mean_r": None if self.mean_r is None else str(self.mean_r),
            "sd_r": None if self.sd_r is None else str(self.sd_r),
            "lower_r": None if self.lower_r is None else str(self.lower_r),
            "max_dd_r": None if self.max_dd_r is None else str(self.max_dd_r),
            "sum_r": None if self.sum_r is None else str(self.sum_r),
        }


@dataclass(frozen=True)
class ExamReport:
    at: str
    champion: Series
    challenger: Series
    n_min: int
    passed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "champion": self.champion.to_payload(),
            "challenger": self.challenger.to_payload(),
            "n_min": self.n_min,
            "passed": self.passed,
            "reasons": list(self.reasons),
        }


def _series(role: str, rows: Iterable[Mapping[str, Any]]) -> Series:
    rs: list[Decimal] = []
    for row in sorted(rows, key=lambda r: str(r.get("closed_at") or "")):
        if row.get("entry_px") in (None, "") or row.get("r_net") in (None, ""):
            continue
        try:
            rs.append(Decimal(str(row["r_net"])))
        except ArithmeticError:
            continue
    n = len(rs)
    if n == 0:
        return Series(role, 0, None, None, None, None, None)
    mean = sum(rs, Decimal(0)) / Decimal(n)
    sd: Decimal | None = None
    lower: Decimal | None = None
    if n >= 2:
        var = sum(((r - mean) ** 2 for r in rs), Decimal(0)) / Decimal(n - 1)
        sd = var.sqrt()
        lower = mean - Z95 * sd / Decimal(n).sqrt()
    cum = Decimal(0)
    peak = Decimal(0)
    dd = Decimal(0)
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return Series(role, n, mean, sd, lower, dd, sum(rs, Decimal(0)))


def exam(
    paper_rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    n_min: int | None = None,
    challenger_sources: frozenset[str] = CHALLENGER_SOURCES,
) -> ExamReport:
    rows = list(paper_rows)
    champ = _series("champion", (r for r in rows if r.get("source") in CHAMPION_SOURCES))
    chal = _series("challenger", (r for r in rows if r.get("source") in challenger_sources))
    limit = mature_n() if n_min is None else n_min
    reasons: list[str] = []
    if chal.n < limit:
        reasons.append(f"challenger n={chal.n} < {limit}")
    if champ.n < limit:
        reasons.append(f"champion n={champ.n} < {limit}")
    if chal.mean_r is None or champ.mean_r is None:
        reasons.append("no expectancy")
    else:
        if chal.mean_r <= champ.mean_r:
            reasons.append("challenger expectancy not above champion")
        if chal.lower_r is None or chal.lower_r <= 0:
            reasons.append("challenger lower bound of mean R not above 0")
        if (
            chal.max_dd_r is not None
            and champ.max_dd_r is not None
            and chal.max_dd_r > champ.max_dd_r
        ):
            reasons.append("challenger drawdown deeper than champion")
    return ExamReport(
        at=now.isoformat(),
        champion=champ,
        challenger=chal,
        n_min=limit,
        passed=not reasons,
        reasons=tuple(reasons),
    )
