"""Halt thresholds live in RiskConfig (SQLite, operator menu). The yaml gates and the
module defaults must agree with it, or the console would show one number and the desk
trade another (audit §3.4)."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.ops.thresholds import load_gates
from capitalizator.risk import halts
from capitalizator.risk.config import RiskConfig


def test_halt_thresholds_agree_everywhere() -> None:
    cfg = RiskConfig()
    assert cfg.day_halt == halts.DAY == Decimal("-0.03")
    assert cfg.week_halt == halts.WEEK == Decimal("-0.06")
    assert cfg.peak_kill == halts.PEAK == Decimal("-0.25")
    g = load_gates()
    kill = g.get("f5") or {}
    yaml_day = kill.get("day_halt", kill.get("day"))
    yaml_week = kill.get("week_halt", kill.get("week"))
    yaml_peak = kill.get("peak_kill", kill.get("peak"))
    if yaml_day is not None:
        assert Decimal(str(yaml_day)) == cfg.day_halt
    if yaml_week is not None:
        assert Decimal(str(yaml_week)) == cfg.week_halt
    if yaml_peak is not None:
        assert Decimal(str(yaml_peak)) == cfg.peak_kill


def test_halt_day_rolls_on_the_session_calendar() -> None:
    """23:30 UTC and 00:30 UTC are the same Moscow day (02:30 / 03:30 MSK)? No — but
    21:30 UTC (00:30 MSK) starts a new Moscow day while UTC is still yesterday."""
    from datetime import UTC, datetime

    from capitalizator.risk.account import Account

    acct = Account(config=RiskConfig())
    acct.roll(datetime(2026, 9, 3, 20, 30, tzinfo=UTC))  # 23:30 MSK, 3 Sep
    day_before = acct._day
    acct.roll(datetime(2026, 9, 3, 21, 30, tzinfo=UTC))  # 00:30 MSK, 4 Sep → new day
    assert acct._day != day_before and acct._day == "2026-09-04"
