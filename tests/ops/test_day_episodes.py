"""No episode file → 0 rows. Does not invent a trade."""

from __future__ import annotations

import json

import pytest

from capitalizator.ops.day_episodes import main


def test_missing_file_is_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--date", "2026-08-31"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n"] == 0
    assert out["episodes"] == []
