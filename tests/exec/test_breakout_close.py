"""3.13.2 — flag off or wick → no breakout. Close+eaten+BTC is not enough if off."""

from __future__ import annotations

from pathlib import Path

from capitalizator.exec.breakout_close import BreakoutClose
from capitalizator.ops.phase import breakout_enabled

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec"


def test_phase_flag_is_off() -> None:
    assert breakout_enabled() is False


def test_all_green_still_false_when_flag_off() -> None:
    assert (
        BreakoutClose.allow(
            enabled=False,
            close_beyond=True,
            tape_eaten=True,
            btc_same=True,
            first_minute=False,
        )
        is False
    )


def test_wick_is_not_close_beyond() -> None:
    assert (
        BreakoutClose.allow(
            enabled=True,
            close_beyond=False,
            tape_eaten=True,
            btc_same=True,
            first_minute=False,
        )
        is False
    )


def test_first_minute_rejects_even_if_enabled() -> None:
    assert (
        BreakoutClose.allow(
            enabled=True,
            close_beyond=True,
            tape_eaten=True,
            btc_same=True,
            first_minute=True,
        )
        is False
    )


def test_close_eaten_btc_when_enabled() -> None:
    assert (
        BreakoutClose.allow(
            enabled=True,
            close_beyond=True,
            tape_eaten=True,
            btc_same=True,
            first_minute=False,
        )
        is True
    )


def test_bounce_does_not_import_breakout_close() -> None:
    text = (SRC / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "BreakoutClose" not in text
    assert "strategy_breakout" not in text
    assert not (SRC / "strategy_breakout.py").is_file()
