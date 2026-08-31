"""3.15.4 — one wallet / sole whale claim is never an entry.

Does not ingest Hyperliquid. Does not invent a cohort.
Voice is never accept. Does not open size.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

WHALE_TYPES = frozenset({"whale", "whale_bought", "wallet"})


def _type_of(claim: Any) -> str:
    if isinstance(claim, str):
        return claim
    if isinstance(claim, dict):
        return str(claim.get("type") or "")
    return str(getattr(claim, "type", "") or "")


def is_whale_claim(claim: Any) -> bool:
    text = _type_of(claim).strip().lower()
    return text in WHALE_TYPES or text.startswith("whale")


def sole_whale(claims: Sequence[Any]) -> bool:
    if not claims:
        return False
    return all(is_whale_claim(c) for c in claims)


def whale_accepts() -> bool:
    """Whale voice is never accept."""
    return False
