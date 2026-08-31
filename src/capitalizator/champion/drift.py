"""0.4.8 — Page-Hinkley on a synthetic 0/1 error series. No live money.

Detects an *increase* in the mean. Fixture: frequency 0.3 then 0.7.
delta / lambda are the textbook knobs for that fixture, not a live threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DriftResult:
    drift: bool
    t: int | None
    n: int


class PageHinkley:
    def __init__(self, *, delta: float = 0.05, threshold: float = 8.0) -> None:
        if delta <= 0 or threshold <= 0:
            raise ValueError("delta and threshold must be > 0")
        self.delta = delta
        self.threshold = threshold

    def run(self, errors: Sequence[int]) -> DriftResult:
        if not errors:
            raise ValueError("empty series")
        total = 0.0
        cusum = 0.0
        trough = 0.0
        for i, bit in enumerate(errors, start=1):
            if bit not in (0, 1):
                raise ValueError("errors must be 0 or 1")
            total += bit
            mean = total / i
            cusum += bit - mean - self.delta
            if cusum < trough:
                trough = cusum
            if cusum - trough >= self.threshold:
                return DriftResult(drift=True, t=i, n=len(errors))
        return DriftResult(drift=False, t=None, n=len(errors))
