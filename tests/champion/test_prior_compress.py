"""prior_compress looks at earlier closed bars, not the current label."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.patterns.cav import label, prior_compress
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


def _atr15() -> list[Bar]:
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    px = Decimal("101")
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=px,
                high=px + Decimal("1"),
                low=px - Decimal("1"),
                close=px,
            )
        )
    return closed


def test_current_compress_is_not_had_compress() -> None:
    tight = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    history = _atr15()
    assert label(ZONE, tight, t=T, htf_bias="box", closed_bars=history) == "COMPRESS"
    assert prior_compress(ZONE, tight, t=T, htf_bias="box", closed_bars=history) is False


def test_earlier_compress_counts() -> None:
    history = _atr15()
    compress = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    through = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("99.5"),
        close=Decimal("99.8"),
    )
    closed = [*history, compress]
    assert label(ZONE, compress, t=T, htf_bias="box", closed_bars=history) == "COMPRESS"
    assert prior_compress(ZONE, through, t=T, htf_bias="box", closed_bars=closed) is True
