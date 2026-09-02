"""Immune memory: traps by idea; Wilson LB; ≥20 look-alikes to recognise; roundtrip."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.oko.memory import (
    N_MIN,
    ImmuneMemory,
    hamming,
    is_trap,
    needed_outcome,
    wilson_lower,
)

TS = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
FP = (0, 3, 0, 0, 3, 1, 4, 1, 0, 0, 0, 0, 3)


def test_trap_is_relative_to_the_idea() -> None:
    assert needed_outcome("bounce") == "bounce"
    assert needed_outcome("failed_break") == "bounce"
    assert needed_outcome("breakout") == "break"
    assert is_trap(idea="bounce", outcome="break") is True
    assert is_trap(idea="bounce", outcome="bounce") is False
    assert is_trap(idea="breakout", outcome="bounce") is True
    assert is_trap(idea="breakout", outcome="die") is None
    with pytest.raises(ValueError):
        is_trap(idea="scalp", outcome="break")
    with pytest.raises(ValueError):
        is_trap(idea="bounce", outcome="pending")


def test_wilson_lower_bound_known_values() -> None:
    assert abs(wilson_lower(15, 20) - 0.5310) < 1e-3
    assert abs(wilson_lower(10, 20) - 0.2993) < 1e-3
    assert wilson_lower(0, 20) == 0.0
    assert abs(wilson_lower(20, 20) - 0.8389) < 1e-3
    with pytest.raises(ValueError):
        wilson_lower(21, 20)


def test_hamming() -> None:
    assert hamming(FP, FP) == 0
    assert hamming(FP, (1, *FP[1:])) == 1
    with pytest.raises(ValueError):
        hamming(FP, FP[:-1])


def test_below_twenty_observes_but_does_not_recognise() -> None:
    mem = ImmuneMemory("BTCUSDT")
    for _ in range(N_MIN - 1):
        mem.learn(FP, idea="bounce", outcome="break", ts=TS)
    rec = mem.recognise(FP, idea="bounce")
    assert rec.n == N_MIN - 1
    assert rec.traps == N_MIN - 1
    assert rec.trap_rate == 1.0
    assert rec.recognised is False


def test_twenty_traps_are_recognised_neighbours_count() -> None:
    mem = ImmuneMemory("BTCUSDT")
    near = (*FP[:-1], 1)  # Hamming 1
    far = (1, 0, *FP[2:])  # Hamming 2
    for i in range(N_MIN):
        mem.learn(FP if i % 2 else near, idea="bounce", outcome="break", ts=TS)
    mem.learn(far, idea="bounce", outcome="break", ts=TS)
    rec = mem.recognise(FP, idea="bounce")
    assert rec.n == N_MIN
    assert rec.recognised is True
    assert rec.lower_bound is not None and rec.lower_bound > 0.5


def test_fifteen_of_twenty_is_on_the_edge_and_recognised() -> None:
    mem = ImmuneMemory("BTCUSDT")
    for i in range(20):
        mem.learn(FP, idea="bounce", outcome="break" if i < 15 else "bounce", ts=TS)
    assert mem.recognise(FP, idea="bounce").recognised is True
    mem2 = ImmuneMemory("BTCUSDT")
    for i in range(20):
        mem2.learn(FP, idea="bounce", outcome="break" if i < 14 else "bounce", ts=TS)
    assert mem2.recognise(FP, idea="bounce").recognised is False


def test_family_separates_bounce_and_break_ideas() -> None:
    mem = ImmuneMemory("BTCUSDT")
    for _ in range(25):
        mem.learn(FP, idea="bounce", outcome="break", ts=TS)
    assert mem.recognise(FP, idea="bounce").recognised is True
    assert mem.recognise(FP, idea="failed_break").recognised is True
    assert mem.recognise(FP, idea="breakout").n == 0


def test_die_is_not_learned_and_memory_is_bounded() -> None:
    mem = ImmuneMemory("BTCUSDT", max_records=N_MIN)
    assert mem.learn(FP, idea="bounce", outcome="die", ts=TS) is None
    assert mem.n == 0
    for _ in range(N_MIN + 5):
        mem.learn(FP, idea="bounce", outcome="bounce", ts=TS)
    assert mem.n == N_MIN


def test_roundtrip() -> None:
    mem = ImmuneMemory("ETHUSDT")
    mem.learn(FP, idea="bounce", outcome="break", ts=TS)
    mem.learn(FP, idea="breakout", outcome="break", ts=TS)
    back = ImmuneMemory.from_dict(mem.to_dict())
    assert back.symbol == "ETHUSDT"
    assert list(back.records) == list(mem.records)
    with pytest.raises(ValueError):
        ImmuneMemory.from_dict({"symbol": "X", "records": "no"})
    with pytest.raises(ValueError):
        ImmuneMemory("")
