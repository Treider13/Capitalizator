"""Bifet/Gavalda ADWIN via online-ml/river. Contour A must not import this file.

river is the extra in pyproject (`hyexec`). We do not reimplement the detector.
"""

from __future__ import annotations

from collections.abc import Sequence


def drift_on(values: Sequence[float]) -> bool:
    """True when river.drift.ADWIN flags a mean shift in `values`."""
    drifted, _ = push(values, detector=None)
    return drifted


def push(
    values: Sequence[float], *, detector: object | None = None
) -> tuple[bool, object]:
    """Online update. Replaying the whole history every tick is not this."""
    from river.drift import ADWIN

    det = ADWIN() if detector is None else detector
    drifted = False
    for value in values:
        det.update(float(value))
        if det.drift_detected:
            drifted = True
    return drifted, det
