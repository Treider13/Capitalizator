"""2.12.5 — monthly greed cuts. Hourly buy-fear is reject, not a short."""

from __future__ import annotations

from capitalizator.news_macro.sentiment import decide


def test_monthly_greed_is_derisk() -> None:
    got = decide(window="month", extreme_greed=True)
    assert got.action == "reject"
    assert got.reason == "monthly_greed"


def test_hour_window_is_not_buy_fear() -> None:
    got = decide(window="hour", extreme_greed=False)
    assert got.action == "reject"
    assert got.reason == "sentiment_not_month"


def test_month_without_extreme_is_ok() -> None:
    got = decide(window="month", extreme_greed=False)
    assert got.action == "accept"
