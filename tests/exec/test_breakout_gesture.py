"""3.13.3 — DEFEND after a puncture is fake_defend, not a chase."""

from __future__ import annotations

from pathlib import Path

from capitalizator.exec.breakout_gesture import FAKE_DEFEND, skip_reason

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec" / "strategy_bounce.py"


def test_defend_after_close_beyond_is_fake_defend() -> None:
    assert skip_reason(gesture="DEFEND", close_beyond=True) == FAKE_DEFEND


def test_retreat_after_close_is_not_this_skip() -> None:
    assert skip_reason(gesture="RETREAT", close_beyond=True) is None


def test_defend_without_puncture_is_not_fake() -> None:
    assert skip_reason(gesture="DEFEND", close_beyond=False) is None


def test_bounce_does_not_import_fake_defend() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "fake_defend" not in text
    assert "skip_reason" not in text
