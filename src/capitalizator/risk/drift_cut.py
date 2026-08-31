"""4.19.2 paper — drift → target 0.5%. Does not write phase.yaml.

Does not raise risk. Does not open size. Detection is passed in.
"""

from __future__ import annotations

from decimal import Decimal

BASE = Decimal("0.01")
DRIFT_TARGET = Decimal("0.005")


def target_after_drift(*, drift: bool, base: Decimal = BASE) -> Decimal:
    if base <= 0:
        raise ValueError("base must be > 0")
    if drift:
        return DRIFT_TARGET
    return base
