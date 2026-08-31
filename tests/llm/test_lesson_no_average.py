"""5.24 paper — lesson/summary cannot say 'долей' or average_in."""

from __future__ import annotations

from capitalizator.llm.daily_summary import DailySummary


def test_doley_is_not_advice() -> None:
    out = DailySummary().run("мало сделок, долей позицию")
    assert out["trade_advice"] is False
    text = out["summary"].lower()
    assert "долей" not in text
    assert "average_in" not in text


def test_average_in_is_stripped() -> None:
    out = DailySummary().run("average_in on the next dip")
    assert out["trade_advice"] is False
    assert "average_in" not in out["summary"].lower()
