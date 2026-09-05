"""Point-in-time feature row from closed 1m/5m/1h bars. Future closes do not exist."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from capitalizator.types import require_utc
from capitalizator.zones.model import Bar


class FeatureError(ValueError):
    """as_of is naive, or a bar leaks past the clock."""


NAMES = (
    "ret_1m",
    "ret_5m",
    "ret_1h",
    "close_5m",
    "high_5m",
    "low_5m",
    "range_5m",
)


@dataclass(frozen=True)
class FeatureRow:
    as_of: datetime
    vector: dict[str, Decimal | None]
    used_close_ts: tuple[datetime, ...]
    close_5m: Decimal | None
    high_5m: Decimal | None
    low_5m: Decimal | None
    NAMES: tuple[str, ...] = NAMES


def _closed(bars: Sequence[Bar], as_of: datetime) -> tuple[Bar, ...]:
    return tuple(sorted((b for b in bars if b.close_ts <= as_of), key=lambda b: b.close_ts))


def _ret(bars: Sequence[Bar]) -> Decimal | None:
    if len(bars) < 2:
        return None
    prev, last = bars[-2], bars[-1]
    if prev.close <= 0:
        return None
    return (last.close - prev.close) / prev.close


def build_features(
    *,
    bars_1m: Sequence[Bar],
    bars_5m: Sequence[Bar],
    bars_1h: Sequence[Bar],
    as_of: datetime,
) -> FeatureRow:
    if as_of.tzinfo is None:
        raise FeatureError("as_of must be UTC")
    when = require_utc(as_of)
    m1 = _closed(bars_1m, when)
    m5 = _closed(bars_5m, when)
    h1 = _closed(bars_1h, when)
    last5 = m5[-1] if m5 else None
    close_5m = None if last5 is None else last5.close
    high_5m = None if last5 is None else last5.high
    low_5m = None if last5 is None else last5.low
    range_5m = None if last5 is None else last5.high - last5.low
    used = tuple(b.close_ts for b in (*m1, *m5, *h1))
    vector: dict[str, Decimal | None] = {
        "ret_1m": _ret(m1),
        "ret_5m": _ret(m5),
        "ret_1h": _ret(h1),
        "close_5m": close_5m,
        "high_5m": high_5m,
        "low_5m": low_5m,
        "range_5m": range_5m,
    }
    return FeatureRow(
        as_of=when,
        vector=vector,
        used_close_ts=used,
        close_5m=close_5m,
        high_5m=high_5m,
        low_5m=low_5m,
    )
