"""DecisionTrace — one row for why contours A/B/C + intel/sentiment/whales agreed.

Not a latency number (that is `decision_ms`). This is the coherent verdict the
operator reads: jury, B gate, challenger, the intel atom that moved B, monthly
sentiment reason, whale/fragility flag.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionTrace:
    touch_id: str
    symbol: str
    closed_at: str
    contour_a: str
    contour_b: str
    contour_c: str
    intel: str | None
    sentiment: str
    whales: str
    skip_reason: str | None
    decision_ms: float

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def intel_atom(pluses: tuple[str, ...], minuses: tuple[str, ...]) -> str | None:
    """The B atom that names a live/calendar fact, if any."""
    named = (
        "fomc_inside_2h",
        "coin_negative",
        "pre_event_24h",
        "whale_only",
        "listing_seen",
    )
    for token in named:
        if token in minuses or token in pluses:
            return token
    for token in pluses:
        if token.startswith("calendar_") or token.startswith("class_"):
            return token
    return None
