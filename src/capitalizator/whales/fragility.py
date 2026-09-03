"""3.15.5 — OI peak ∧ crowded funding ∧ thin book → no new entries on the crowded side.

Inputs are explicit flags computed by the desk from its own tape (OI percentile
over its own history, funding percentile over its own history, book depth against
the ОКО Passport norm). None is unknown: we do not invent a peak.

Longs are forbidden when the crowd is long (funding in the top tail: longs pay)
and the book is thin at an OI peak — the cascade that follows is a long
liquidation. Shorts are the mirror: funding in the bottom tail (shorts pay).
Heatmap is not a magnet. Does not open the opposite side. Does not ingest OI.
"""

from __future__ import annotations


def forbid_new_long(
    *,
    oi_peak: bool | None,
    funding_top5: bool | None,
    thin_book: bool | None,
) -> bool:
    if oi_peak is None or funding_top5 is None or thin_book is None:
        return False
    return oi_peak and funding_top5 and thin_book


def forbid_new_short(
    *,
    oi_peak: bool | None,
    funding_bottom5: bool | None,
    thin_book: bool | None,
) -> bool:
    if oi_peak is None or funding_bottom5 is None or thin_book is None:
        return False
    return oi_peak and funding_bottom5 and thin_book


def heatmap_is_entry() -> bool:
    return False
