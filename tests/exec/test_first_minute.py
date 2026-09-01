"""3.13.2 — first 60s after the breakout bar close is reject. Not a bounce gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capitalizator.exec.first_minute import FirstMinute
from capitalizator.risk.session import load_time_config

CLOSE = datetime(2026, 8, 31, 14, 15, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec"


def test_yaml_first_minute_is_60() -> None:
    assert int(load_time_config()["first_minute_s"]) == 60
    assert FirstMinute().seconds == 60


def test_same_second_as_close_is_blocked() -> None:
    assert FirstMinute().blocks(CLOSE, CLOSE) is True


def test_59s_is_blocked() -> None:
    assert FirstMinute().blocks(CLOSE + timedelta(seconds=59), CLOSE) is True


def test_60s_is_not_blocked() -> None:
    assert FirstMinute().blocks(CLOSE + timedelta(seconds=60), CLOSE) is False


def test_before_close_is_blocked() -> None:
    assert FirstMinute().blocks(CLOSE - timedelta(seconds=1), CLOSE) is True


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(TypeError, match="naive"):
        FirstMinute().blocks(datetime(2026, 8, 31, 14, 15), CLOSE)


def test_bounce_source_uses_first_minute() -> None:
    bounce = (SRC / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "FirstMinute" in bounce
    assert "first_minute" in bounce
