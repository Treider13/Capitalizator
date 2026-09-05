"""Feature vector is point-in-time. A bar that closes after as_of is not a feature."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.hyexec.features import FeatureError, build_features, feature_journal
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


def test_sma5_is_none_until_five_closes() -> None:
    row = build_features(
        bars_1m=(),
        bars_5m=(_bar("5m", AS_OF - timedelta(minutes=5), "98"), _bar("5m", AS_OF, "100")),
        bars_1h=(),
        as_of=AS_OF,
    )
    assert row.vector["sma5_5m"] is None
    assert row.vector["close_vs_sma5"] is None
    assert row.vector["bos_5m"] is None
    assert row.vector["choch_5m"] is None


def test_sma5_is_mean_of_last_five_closed() -> None:
    bars = tuple(
        _bar("5m", AS_OF - timedelta(minutes=5 * (4 - i)), str(100 + i)) for i in range(5)
    )
    row = build_features(bars_1m=(), bars_5m=bars, bars_1h=(), as_of=AS_OF)
    assert row.vector["sma5_5m"] == Decimal("102")
    assert row.vector["close_vs_sma5"] == (Decimal("104") - Decimal("102")) / Decimal("102")


def test_bos_5m_uses_existing_smc_atom() -> None:
    """BOS/CHoCH come from card.smc (joshyattridge/smart-money-concepts), not a new lib."""
    from datetime import timedelta as td

    from capitalizator.card.smc import bos_status

    ohlc = [("100", "101", "99", "100")] * 12
    ohlc = list(ohlc)
    ohlc[5] = ("105", "130", "104", "120")
    ohlc[6] = ("120", "122", "110", "112")
    ohlc[7] = ("112", "118", "108", "110")
    ohlc[8] = ("110", "116", "108", "112")
    ohlc[9] = ("112", "115", "109", "111")
    ohlc[10] = ("111", "114", "108", "110")
    ohlc[11] = ("125", "140", "124", "135")
    bars = []
    for i, (o, h, l, c) in enumerate(ohlc):
        close_ts = AS_OF - td(minutes=5 * (11 - i))
        bars.append(
            Bar(
                symbol="BTCUSDT",
                tf="5m",
                open_ts=close_ts - td(minutes=5),
                close_ts=close_ts,
                open=Decimal(o),
                high=Decimal(h),
                low=Decimal(l),
                close=Decimal(c),
                volume=Decimal("1"),
            )
        )
    assert bos_status(bars) == "bull"
    row = build_features(bars_1m=(), bars_5m=bars, bars_1h=(), as_of=AS_OF)
    assert row.vector["bos_5m"] == Decimal("1")
    assert row.vector["choch_5m"] is None


def test_known_names_only() -> None:
    row = build_features(
        bars_1m=(_bar("1m", AS_OF, "100"), _bar("1m", AS_OF - timedelta(minutes=1), "99")),
        bars_5m=(_bar("5m", AS_OF, "100"), _bar("5m", AS_OF - timedelta(minutes=5), "98")),
        bars_1h=(_bar("1h", datetime(2026, 9, 1, 10, 0, tzinfo=UTC), "99"),),
        as_of=AS_OF,
    )
    extra = set(row.vector) - set(row.NAMES)
    assert extra == set()
    stamped = feature_journal(row)
    assert stamped["hx_ret_1m"] is not None
    assert feature_journal(None)["hx_close_5m"] is None
    assert "ret_1m" in row.vector
    assert "ret_5m" in row.vector
    assert "ret_1h" in row.vector
