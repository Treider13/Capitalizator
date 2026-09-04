"""Э6: the five formerly dead modules are on a live import path."""

from __future__ import annotations

from capitalizator.ops.gen_status import reachability

WIRED = (
    "capitalizator.exec.breakout_gesture",
    "capitalizator.ops.healthz",
    "capitalizator.patterns.exam",
    "capitalizator.recorder.rest_ticker",
    "capitalizator.risk.nmin",
    "capitalizator.news_macro.store",
    "capitalizator.desk.paper_gates",
)


def test_e6_modules_are_reachable() -> None:
    _, unreachable = reachability()
    missing = [name for name in WIRED if name in unreachable]
    assert missing == []
