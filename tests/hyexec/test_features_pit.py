"""Feature vector is point-in-time. A bar that closes after as_of is not a feature."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.hyexec.features import FeatureError, build_features
from capitalizator.zones.model import Bar

AS_OF = datetime(2026, 9, 1, 10, 5, tzinfo=UTC)


def _bar(tf: str, close_ts: datetime, close: str, *, high: str | None = None, low: str | None = None) -> Bar:
    minutes = {"1m": 1, "5m": 5, "1h": 60}[tf]
    px = Decimal(close)
    return Bar(
        symbol="BTCUSDT",
        tf=tf,
        open_ts=close_ts - timedelta(minutes=minutes),
        close_ts=close_ts,
        open=px,
        high=Decimal(high) if high is not None else px,
        low=Decimal(low) if low is not None else px,
        close=px,
        volume=Decimal("1"),
    )


def test_future_five_minute_close_is_dropped() -> None:
    past = _bar("5m", AS_OF, "100")
    future = _bar("5m", AS_OF + timedelta(minutes=5), "130")
    row = build_features(
        bars_1m=(_bar("1m", AS_OF, "100"),),
        bars_5m=(past, future),
        bars_1h=(_bar("1h", datetime(2026, 9, 1, 10, 0, tzinfo=UTC), "99"),),
        as_of=AS_OF,
    )
    assert future.close_ts not in row.used_close_ts
    assert past.close_ts in row.used_close_ts
    assert row.close_5m == Decimal("100")


def test_unclosed_bar_cannot_leak_high() -> None:
    closed = _bar("5m", AS_OF, "100", high="101", low="99")
    unclosed = _bar("5m", AS_OF + timedelta(minutes=5), "100", high="140", low="90")
    row = build_features(
        bars_1m=(_bar("1m", AS_OF, "100"),),
        bars_5m=(closed, unclosed),
        bars_1h=(_bar("1h", datetime(2026, 9, 1, 10, 0, tzinfo=UTC), "99"),),
        as_of=AS_OF,
    )
    assert row.high_5m == Decimal("101")
    assert row.low_5m == Decimal("99")


def test_as_of_must_be_utc() -> None:
    with pytest.raises(FeatureError, match="UTC"):
        build_features(
            bars_1m=(),
            bars_5m=(),
            bars_1h=(),
            as_of=datetime(2026, 9, 1, 10, 5),
        )


def test_known_names_only() -> None:
    row = build_features(
        bars_1m=(_bar("1m", AS_OF, "100"), _bar("1m", AS_OF - timedelta(minutes=1), "99")),
        bars_5m=(_bar("5m", AS_OF, "100"), _bar("5m", AS_OF - timedelta(minutes=5), "98")),
        bars_1h=(_bar("1h", datetime(2026, 9, 1, 10, 0, tzinfo=UTC), "99"),),
        as_of=AS_OF,
    )
    extra = set(row.vector) - set(row.NAMES)
    assert extra == set()
    assert "ret_1m" in row.vector
    assert "ret_5m" in row.vector
    assert "ret_1h" in row.vector
