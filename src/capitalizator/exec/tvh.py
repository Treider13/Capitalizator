"""TVH — точка входа. Journal skip, not a jury voice.

no_tvh when the print is mid-range, tape is unknown, or both CAV and ZLG
lack n>=20. Does not open size. Does not invent a side.
"""

from __future__ import annotations

from capitalizator.jury.desk import CAV_LABELS, N_MIN, ZLG_LABELS

NO_TVH = "no_tvh"
_CAV_OK = frozenset({"REJECT", "THROUGH"})
_ZLG_OK = frozenset({"DEFEND", "RETREAT", "IMPROVE"})


def tvh_ok(
    *,
    price_in_zone: bool,
    mid: bool,
    cav: str | None,
    zlg: str | None,
    n_cav: int,
    n_zlg: int,
    tape_eaten: bool | None,
) -> bool:
    if n_cav < 0 or n_zlg < 0:
        raise ValueError("n must be >= 0")
    if cav is not None and cav not in CAV_LABELS:
        raise ValueError(f"unknown cav: {cav!r}")
    if zlg is not None and zlg not in ZLG_LABELS:
        raise ValueError(f"unknown zlg: {zlg!r}")
    if not price_in_zone or mid:
        return False
    if tape_eaten is None:
        return False
    cav_ready = cav in _CAV_OK and n_cav >= N_MIN
    zlg_ready = zlg in _ZLG_OK and n_zlg >= N_MIN
    return cav_ready or zlg_ready
