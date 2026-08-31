"""3.15.5 — OI peak ∧ funding top-5% ∧ thin book → no new longs.

Inputs are explicit flags. None is unknown: we do not invent a peak.
Heatmap is not a magnet. Does not open a short. Does not ingest OI.
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


def heatmap_is_entry() -> bool:
    return False
