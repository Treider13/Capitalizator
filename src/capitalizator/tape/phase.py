"""AMD phase of the 8s touch window. Missing facts stay unknown. Does not open size.

  manipulate  — tape ate the level and mid is back (sweep then reclaim)
  distribute  — price and both flows (OFI, CVD) agree on a move
  accumulate  — book and tape disagree, mid barely moved
  unknown     — anything else, including a missing input
"""

from __future__ import annotations

from decimal import Decimal

Phase = str


def classify(
    *,
    ofi: Decimal | None,
    cvd: Decimal | None,
    mid_ticks: Decimal | None,
    eaten: bool | None,
) -> Phase:
    if ofi is None or cvd is None or mid_ticks is None:
        return "unknown"
    if eaten is True and abs(mid_ticks) <= 1:
        return "manipulate"
    if (
        mid_ticks != 0
        and (mid_ticks > 0) == (cvd > 0)
        and (mid_ticks > 0) == (ofi > 0)
    ):
        return "distribute"
    if abs(mid_ticks) <= 1 and ofi != 0 and cvd != 0 and (ofi > 0) != (cvd > 0):
        return "accumulate"
    return "unknown"
