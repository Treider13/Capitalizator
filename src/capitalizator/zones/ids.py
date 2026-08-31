"""zone_id = blake2s(symbol, tf, side, lo, hi, method, created_as_of)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from hashlib import blake2s

from capitalizator.book.reconstruct import _canon
from capitalizator.types import require_utc


def make_zone_id(
    *,
    symbol: str,
    tf: str,
    side: str,
    lo: Decimal,
    hi: Decimal,
    method: str,
    created_as_of: datetime,
) -> str:
    created = require_utc(created_as_of).isoformat()
    payload = "|".join(
        (symbol, tf, side, _canon(lo), _canon(hi), method, created)
    ).encode()
    return blake2s(payload, digest_size=16).hexdigest()
