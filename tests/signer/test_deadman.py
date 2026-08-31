"""Silence longer than 30s calls cancel_all. No exchange."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from capitalizator.signer.deadman import DeadMan

T0 = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def test_beat_then_29s_is_alive() -> None:
    hits: list[int] = []
    dm = DeadMan(lambda: hits.append(1))
    dm.beat(T0)
    assert dm.tick(T0 + timedelta(seconds=29)) is False
    assert hits == []


def test_silence_31s_cancels() -> None:
    hits: list[int] = []
    dm = DeadMan(lambda: hits.append(1))
    dm.beat(T0)
    assert dm.tick(T0 + timedelta(seconds=31)) is True
    assert hits == [1]


def test_no_beat_cancels_on_first_tick() -> None:
    hits: list[int] = []
    dm = DeadMan(lambda: hits.append(1))
    assert dm.tick(T0) is True
    assert hits == [1]
