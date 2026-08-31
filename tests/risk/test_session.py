"""12:00 UTC reject, 14:10 UTC accept, 20:00 UTC reject. Night 5x always reject."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.risk.session import allow_entry, in_desk_window


def test_1500_msk_is_closed() -> None:
    noon = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    assert in_desk_window(noon) is False
    ok, reason = allow_entry(noon)
    assert ok is False
    assert reason == "outside session"


def test_1710_msk_is_open() -> None:
    t = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
    assert in_desk_window(t) is True
    ok, reason = allow_entry(t)
    assert ok is True
    assert reason == "session"


def test_2300_msk_is_closed() -> None:
    t = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    ok, reason = allow_entry(t)
    assert ok is False
    assert reason == "outside session"


def test_night_five_x_always_reject() -> None:
    t = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    ok, reason = allow_entry(t, lev=Decimal("5"), no_us_today=True)
    assert ok is False
    assert reason == "night 5x"


def test_no_us_today_logs_bypass() -> None:
    t = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    ok, reason = allow_entry(t, no_us_today=True)
    assert ok is True
    assert reason == "no_us_today"
