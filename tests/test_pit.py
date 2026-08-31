"""−1.4: slice at 12:00Z does not see a fact known at 12:05Z."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.types import MarketEvent, PitInstant, known_by, require_utc


def test_naive_datetime_rejected() -> None:
    with pytest.raises(TypeError, match="naive"):
        require_utc(datetime(2026, 1, 1, 12, 0, 0))


def test_pit_instant_rejects_naive() -> None:
    aware = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    with pytest.raises(TypeError, match="naive"):
        PitInstant(as_of=datetime(2026, 8, 30, 12, 0, 0), known_at=aware)


def test_news_known_after_slice_is_invisible() -> None:
    news = PitInstant(
        as_of=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        known_at=datetime(2026, 8, 30, 12, 5, tzinfo=UTC),
    )
    slice_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    visible = [news] if known_by(news.known_at, slice_at) else []
    assert visible == []


def test_news_known_at_slice_is_visible() -> None:
    news = PitInstant(
        as_of=datetime(2026, 8, 30, 11, 50, tzinfo=UTC),
        known_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )
    slice_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    assert known_by(news.known_at, slice_at) is True


def test_market_event_requires_utc() -> None:
    with pytest.raises(TypeError, match="naive"):
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 12, 0, 0),
            recv_ts=datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC),
            seq=1,
            payload={},
        )
