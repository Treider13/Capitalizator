"""Hour DD cuts size. A timer never retrains. Only an ADWIN flag retrains."""

from __future__ import annotations

from decimal import Decimal

HOUR_DD = Decimal("-0.03")
HOUR_CUT = Decimal("0.5")


def after_hour_dd(*, hour_dd: Decimal, risk: Decimal) -> Decimal:
    if risk <= 0:
        raise ValueError("risk must be > 0")
    if hour_dd <= HOUR_DD:
        return risk * HOUR_CUT
    return risk


def timer_retrain(hours: int) -> bool:
    return False


def should_retrain(*, adwin_drift: bool) -> bool:
    return adwin_drift
