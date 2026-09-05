"""Point-in-time feature row from closed 1m/5m/1h bars. Future closes do not exist."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from capitalizator.card.smc import bos_status
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
    "sma5_5m",
    "close_vs_sma5",
    "bos_5m",
    "choch_5m",
)
SMA5 = 5


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


def _sma(bars: Sequence[Bar], n: int = SMA5) -> Decimal | None:
    if len(bars) < n:
        return None
    closes = [b.close for b in bars[-n:]]
    if any(c <= 0 for c in closes):
        return None
    return sum(closes, Decimal("0")) / Decimal(n)


def _bos_code(bars: Sequence[Bar]) -> Decimal | None:
    side = bos_status(bars)
    if side == "bull":
        return Decimal("1")
    if side == "bear":
        return Decimal("-1")
    return None


def _choch(bars: Sequence[Bar]) -> Decimal | None:
    """1 when the last two confirmed BOS disagree (CHoCH). Else 0. None if <2 BOS."""
    prev: Decimal | None = None
    last: Decimal | None = None
    for i in range(len(bars)):
        code = _bos_code(bars[: i + 1])
        if code is None:
            continue
        if prev is not None and code != prev:
            last = Decimal("1")
        elif prev is not None:
            last = Decimal("0")
        prev = code
    return last


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
    sma5 = _sma(m5)
    close_vs = None if sma5 is None or close_5m is None or sma5 == 0 else (close_5m - sma5) / sma5
    used = tuple(b.close_ts for b in (*m1, *m5, *h1))
    vector: dict[str, Decimal | None] = {
        "ret_1m": _ret(m1),
        "ret_5m": _ret(m5),
        "ret_1h": _ret(h1),
        "close_5m": close_5m,
        "high_5m": high_5m,
        "low_5m": low_5m,
        "range_5m": range_5m,
        "sma5_5m": sma5,
        "close_vs_sma5": close_vs,
        "bos_5m": _bos_code(m5),
        "choch_5m": _choch(m5),
    }
    return FeatureRow(
        as_of=when,
        vector=vector,
        used_close_ts=used,
        close_5m=close_5m,
        high_5m=high_5m,
        low_5m=low_5m,
    )
