"""HTF RSI for contour B. Wilder RSI, period 14. Never imported by A.

Prefers TA-Lib `stream.RSI` + `set_unstable_period('RSI', 100)` when the C
extension is present. Otherwise the same Wilder seed + smooth, in-repo.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from importlib import import_module
from types import ModuleType

import numpy as np

from capitalizator.card.params import RSI_HTF_TF, RSI_PERIOD, RSI_UNSTABLE_PERIOD
from capitalizator.zones.model import Bar

_TF_MINUTES = {"1h": 60, "4h": 240}

talib: ModuleType | None
try:
    talib = import_module("talib")

    talib.set_unstable_period("RSI", RSI_UNSTABLE_PERIOD)
    _TALIB = True
except (ImportError, AttributeError):  # pragma: no cover - extension optional
    talib = None
    _TALIB = False


def rsi_htf(
    bars: Sequence[Bar],
    *,
    period: int = RSI_PERIOD,
    unstable: int = RSI_UNSTABLE_PERIOD,
) -> str | None:
    """Latest HTF RSI as a decimal string, or None when the series is short."""
    closes = _htf_closes(bars)
    value = stream_rsi(closes, period=period, unstable=unstable)
    if value is None:
        return None
    return f"{value:.2f}"


def stream_rsi(
    closes: Sequence[float | Decimal],
    *,
    period: int = RSI_PERIOD,
    unstable: int = RSI_UNSTABLE_PERIOD,
) -> float | None:
    """One-step Wilder RSI. TA-Lib stream path when installed."""
    series = [float(x) for x in closes]
    if len(series) < period + unstable + 1:
        return None
    if _TALIB:
        return _talib_stream(series, period=period)
    return _wilder_rsi(series, period=period, unstable=unstable)


def _talib_stream(closes: list[float], *, period: int) -> float | None:
    assert talib is not None
    arr = np.asarray(closes, dtype=float)
    raw = talib.stream.RSI(arr, timeperiod=period)
    if raw is None:
        return None
    value = float(raw)
    if value != value:  # NaN
        return None
    return value


def _wilder_rsi(closes: list[float], *, period: int, unstable: int) -> float | None:
    """SMA seed over `period` changes, then Wilder smooth. Same as TA-Lib RSI."""
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(closes, closes[1:], strict=False):
        delta = cur - prev
        gains.append(delta if delta > 0 else 0.0)
        losses.append(-delta if delta < 0 else 0.0)
    if len(gains) < period:
        return None
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    n_rsi = 1
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        n_rsi += 1
    if n_rsi <= unstable:
        return None
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _htf_closes(bars: Sequence[Bar]) -> list[float]:
    picked = _pick_htf(bars)
    return [float(b.close) for b in picked]


def _pick_htf(bars: Sequence[Bar]) -> list[Bar]:
    need = RSI_PERIOD + RSI_UNSTABLE_PERIOD + 1
    by_tf = {tf: [b for b in bars if b.tf == tf] for tf in RSI_HTF_TF}
    for tf in RSI_HTF_TF:
        if len(by_tf[tf]) >= need:
            return by_tf[tf]
    resampled = _resample(bars, "1h")
    if len(resampled) >= need:
        return resampled
    for tf in RSI_HTF_TF:
        if by_tf[tf]:
            return by_tf[tf]
    return resampled


def _resample(bars: Sequence[Bar], tf: str) -> list[Bar]:
    minutes = _TF_MINUTES[tf]
    src = [b for b in bars if b.tf == "15m"] or list(bars)
    if not src:
        return []
    buckets: dict[datetime, list[Bar]] = {}
    for bar in src:
        total = bar.open_ts.hour * 60 + bar.open_ts.minute
        floor = total - (total % minutes)
        open_ts = bar.open_ts.replace(
            hour=floor // 60, minute=floor % 60, second=0, microsecond=0
        )
        buckets.setdefault(open_ts, []).append(bar)
    out: list[Bar] = []
    span = timedelta(minutes=minutes)
    for open_ts, group in sorted(buckets.items()):
        group = sorted(group, key=lambda b: b.open_ts)
        close_ts = open_ts + span - timedelta(microseconds=1)
        if group[-1].close_ts < close_ts and len(group) * 15 < minutes:
            continue
        vol = sum((b.volume or Decimal("0") for b in group), Decimal("0"))
        out.append(
            Bar(
                symbol=group[0].symbol,
                tf=tf,
                open_ts=open_ts,
                close_ts=group[-1].close_ts,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=vol,
            )
        )
    return out
