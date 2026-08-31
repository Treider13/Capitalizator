"""Hostile exam of a price/vol forecast. Contour C later. Not an entry.

Beats last-price, residual after ATR, share of profit in the best 5 days,
direction hit and vol-rank Spearman IC are reported separately.
Does not open size. Pure Decimal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExamCase:
    pred: Decimal
    last: Decimal
    actual: Decimal
    atr: Decimal | None = None
    day: date | None = None
    pred_vol_rank: Decimal | None = None
    actual_vol: Decimal | None = None
    pnl: Decimal | None = None


@dataclass(frozen=True)
class HostileExam:
    n: int
    beat_last_price: Decimal | None
    residual_after_atr: Decimal | None
    pnl_share_best_5_days: Decimal | None
    direction_hit: Decimal | None
    vol_rank_ic: Decimal | None


def hostile_exam(cases: Sequence[ExamCase]) -> HostileExam:
    """Score a finished sample. Not a live gate and not a size."""
    rows = list(cases)
    n = len(rows)
    if n == 0:
        return HostileExam(
            n=0,
            beat_last_price=None,
            residual_after_atr=None,
            pnl_share_best_5_days=None,
            direction_hit=None,
            vol_rank_ic=None,
        )
    return HostileExam(
        n=n,
        beat_last_price=_beat_last_price(rows),
        residual_after_atr=_residual_after_atr(rows),
        pnl_share_best_5_days=_pnl_share_best_5_days(rows),
        direction_hit=_direction_hit(rows),
        vol_rank_ic=_vol_rank_ic(rows),
    )


def _beat_last_price(rows: Sequence[ExamCase]) -> Decimal:
    beats = sum(1 for c in rows if abs(c.pred - c.actual) < abs(c.last - c.actual))
    return Decimal(beats) / Decimal(len(rows))


def _residual_after_atr(rows: Sequence[ExamCase]) -> Decimal | None:
    xs = [abs(c.pred - c.actual) / c.atr for c in rows if c.atr is not None and c.atr > 0]
    if not xs:
        return None
    return _median(xs)


def _pnl_share_best_5_days(rows: Sequence[ExamCase]) -> Decimal | None:
    by_day: dict[date, Decimal] = {}
    for case in rows:
        if case.day is None or case.pnl is None:
            continue
        by_day[case.day] = by_day.get(case.day, Decimal("0")) + case.pnl
    if len(by_day) < 5:
        return None
    total = sum(by_day.values(), Decimal("0"))
    if total <= 0:
        return None
    top = sorted(by_day.values(), reverse=True)[:5]
    return sum(top, Decimal("0")) / total


def _direction_hit(rows: Sequence[ExamCase]) -> Decimal | None:
    directed = [c for c in rows if c.pred != c.last]
    if not directed:
        return None
    hits = sum(1 for c in directed if _sign(c.pred - c.last) == _sign(c.actual - c.last))
    return Decimal(hits) / Decimal(len(directed))


def _vol_rank_ic(rows: Sequence[ExamCase]) -> Decimal | None:
    pairs = [
        (c.pred_vol_rank, c.actual_vol)
        for c in rows
        if c.pred_vol_rank is not None and c.actual_vol is not None
    ]
    if len(pairs) < 2:
        return None
    pred_ranks = _ranks([p for p, _ in pairs])
    actual_ranks = _ranks([a for _, a in pairs])
    return _pearson(pred_ranks, actual_ranks)


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _median(xs: Sequence[Decimal]) -> Decimal:
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2:
        return ys[mid]
    return (ys[mid - 1] + ys[mid]) / Decimal("2")


def _ranks(values: Sequence[Decimal]) -> list[Decimal]:
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [Decimal("0")] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (Decimal(i) + Decimal(j)) / Decimal("2") + Decimal("1")
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    count = Decimal(n)
    mx = sum(xs, Decimal("0")) / count
    my = sum(ys, Decimal("0")) / count
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx == 0 or dy == 0:
        return None
    return num / (dx.sqrt() * dy.sqrt())
