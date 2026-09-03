"""One home for the small statistics every module used to re-implement.

Wilson score interval (95% by default) in Decimal and in float, and the
"enough observations" thresholds read from `infra/registry.yaml` so that the
jury, the ОКО organs, the calibration and the first fact agree on what "n≥20"
and "mature n≥30" mean (audit §3.3: nine copies, three z values).
"""

from __future__ import annotations

import math
from decimal import Decimal
from functools import lru_cache

Z95 = Decimal("1.959963984540054")  # two-sided 95% (Wilson intervals)
Z95_F = 1.959963984540054
Z95_ONE_SIDED = Decimal("1.6448536269514722")  # one-sided 95% bounds of a mean


def wilson_interval(wins: int, n: int, *, z: Decimal = Z95) -> tuple[Decimal, Decimal]:
    """Wilson score interval for a binomial proportion, clipped to [0, 1]."""
    if n <= 0:
        raise ValueError("n must be > 0")
    if wins < 0 or wins > n:
        raise ValueError("wins must be within [0, n]")
    p = Decimal(wins) / Decimal(n)
    nn = Decimal(n)
    denom = 1 + z * z / nn
    centre = (p + z * z / (2 * nn)) / denom
    half = z * ((p * (1 - p) / nn + z * z / (4 * nn * nn)) ** Decimal("0.5")) / denom
    return max(Decimal(0), centre - half), min(Decimal(1), centre + half)


def wilson_lower_f(k: int, n: int, *, z: float = Z95_F) -> float:
    """Float Wilson lower bound (ОКО memory hot path)."""
    if n <= 0 or k < 0 or k > n:
        raise ValueError("wilson needs 0 <= k <= n, n > 0")
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    adj = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - adj) / denom)


@lru_cache(maxsize=1)
def thresholds() -> tuple[int, int]:
    """(n_min, mature_n) from registry.yaml. Cached: the file is frozen per phase."""
    from capitalizator.zones.config import load_registry

    cfg = load_registry()
    return cfg.n_min, cfg.mature_n


def n_min() -> int:
    """Observations before a label / class may vote or be trusted (default 20)."""
    return thresholds()[0]


def mature_n() -> int:
    """Observations before a norm / interval is narrow enough to refute (default 30)."""
    return thresholds()[1]
