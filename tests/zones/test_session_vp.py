"""Session VAP zones: last closed sessions.yaml window, no lookahead, no invented POC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.risk.sessions import SessionPolicy
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Bar
from capitalizator.zones.session_vp import last_closed_bounds, session_profile

TICK = Decimal("0.1")
WORKING = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)  # wednesday europe window


def _bar(
    close_ts: datetime,
    *,
    low: str,
    high: str,
    close: str,
    volume: str | None = "10",
    tf: str = "15m",
) -> Bar:
    open_ts = close_ts - timedelta(minutes=15)
    return Bar(
        symbol="BTCUSDT",
        tf=tf,
        open_ts=open_ts,
        close_ts=close_ts,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=None if volume is None else Decimal(volume),
    )


def test_asia_bars_do_not_build_europe_vp() -> None:
    asia_close = datetime(2026, 9, 2, 3, 15, tzinfo=UTC)
    bars = [_bar(asia_close, low="90", high="92", close="91", volume="50")]
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", WORKING, bars)
    europe = [z for z in zones if z.method == "session_vp_europe"]
    asia = [z for z in zones if z.method == "session_vp_asia"]
    assert asia
    assert not europe


def test_future_bar_is_not_in_profile() -> None:
    future = datetime(2026, 9, 2, 11, 0, tzinfo=UTC)
    past = datetime(2026, 9, 2, 3, 15, tzinfo=UTC)
    bars = [
        _bar(past, low="90", high="91", close="90.5", volume="10"),
        _bar(future, low="100", high="120", close="110", volume="999"),
    ]
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", WORKING, bars)
    asia = [z for z in zones if z.method == "session_vp_asia" and z.side == "resistance"]
    assert asia
    assert all(z.hi < Decimal("100") for z in asia)


def test_zero_volume_is_no_zone() -> None:
    bars = [_bar(datetime(2026, 9, 2, 3, 15, tzinfo=UTC), low="90", high="91", close="90.5", volume=None)]
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", WORKING, bars)
    assert not any(z.method.startswith("session_vp_") for z in zones)


def test_two_runs_same_zone_id() -> None:
    bars = [_bar(datetime(2026, 9, 2, 3, 15, tzinfo=UTC), low="90", high="92", close="91", volume="20")]
    engine = ZoneEngine(tick_size=TICK)
    a = engine.build("BTCUSDT", WORKING, bars)
    b = engine.build("BTCUSDT", WORKING, bars)
    assert [z.zone_id for z in a] == [z.zone_id for z in b]


def test_prior_session_hl_still_exists() -> None:
    """MSK 16:30 window is not deleted by session VP."""
    # previous Moscow desk window 13:30–16:30 UTC on Sep 1 relative to WORKING Sep 2 10:00
    bars = [
        _bar(datetime(2026, 8, 31, 14, 0, tzinfo=UTC), low="80", high="85", close="82", volume="5"),
        _bar(datetime(2026, 9, 2, 3, 15, tzinfo=UTC), low="90", high="92", close="91", volume="20"),
    ]
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", WORKING, bars)
    assert any(z.method == "prior_session_hl" for z in zones)
    assert any(z.method == "session_vp_asia" for z in zones)


def test_profile_empty_without_volume() -> None:
    bars = [_bar(datetime(2026, 9, 2, 3, 15, tzinfo=UTC), low="90", high="91", close="90.5", volume=None)]
    assert session_profile(bars, tick=TICK) is None


def test_last_closed_asia_is_today_when_europe_is_open() -> None:
    policy = SessionPolicy.load()
    bounds = last_closed_bounds(policy.window_named("asia"), WORKING)
    assert bounds is not None
    start, end = bounds
    assert start == datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 2, 7, 0, tzinfo=UTC)
