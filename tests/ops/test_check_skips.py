"""No skip file → n=0 exit 2. A written skip is not a trade."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from capitalizator.ops.check_skips import main
from capitalizator.ops.skip_log import SkipLog


def test_missing_file_is_not_a_green_week(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--days", "7"])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["n"] == 0
    assert out["ok"] is False


def test_skip_log_keeps_reason() -> None:
    log = SkipLog()
    log.add("середина", datetime(2026, 8, 31, 14, 0, tzinfo=UTC))
    rows = log.last_days(7, now=datetime(2026, 8, 31, 18, 0, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0].reason == "середина"
