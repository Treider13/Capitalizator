"""CAV: closed bar only. Wick+close inside = REJECT. Close beyond = THROUGH."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.patterns.cav import label
from capitalizator.zones.model import Bar, Zone

T = datetime(2026, 8, 30, 16, 45, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="swing",
    created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
)


def _bar(*, low: str, high: str, close: str, close_ts: datetime | None = None) -> Bar:
    end = close_ts or datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=end,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_unclosed_bar_is_noise() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1", close_ts=T)
    assert label(ZONE, bar, t=T, htf_bias="box") == "NOISE"


def test_wick_in_close_inside_is_reject() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box") == label(ZONE, bar, t=T, htf_bias="box")


def test_close_beyond_support_is_through() -> None:
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"


def test_htf_against_is_noise() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="short") == "NOISE"


def test_mid_range_miss_is_noise() -> None:
    bar = _bar(low="110", high="111", close="110.5")
    assert label(ZONE, bar, t=T, htf_bias="box") == "NOISE"


def test_close_inside_without_wick_beyond_is_drift() -> None:
    """INVENTION-JURY: in the zone, no reject, no close beyond → DRIFT."""
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"


def test_small_range_inside_zone_is_compress() -> None:
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"
