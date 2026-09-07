"""Third audit: continuity, snapshot ownership and configuration invariants."""

from dataclasses import replace

import pytest
from tests.fusion.test_liquidation_pressure import Feed

from capitalizator.fusion.liquidation_pressure import PressureConfig


def recovered():
    feed = Feed()
    feed.warm()
    feed.wave()
    for _ in range(48):
        feed.second(99.5)
    assert feed.observer.episodes["sell"].state == "recovery"
    return feed


def test_fresh_trade_cannot_resurrect_recovery_after_trade_outage():
    feed = recovered()
    for _ in range(7):
        feed.at += 1
        feed.market.book_at = feed.market.book_exchange_at = feed.at
        feed.event("book", {})
    assert feed.observer.snapshot()["quality"] == "unavailable"
    feed.second(99.5)
    feed.second(99.5)
    assert feed.observer.episodes["sell"].state != "recovery"
    assert "Buy" in feed.observer.snapshot()["would_block"]


def test_snapshot_expires_at_underlying_trade_deadline_before_next_calculation():
    feed = recovered()
    last_trade = feed.observer.last_trade_at
    for _ in range(5):
        feed.at += 1
        feed.market.book_at = feed.market.book_exchange_at = feed.at
        feed.event("book", {})
    assert feed.observer.snapshot()["quality"] == "ready"
    assert feed.observer.snapshot(last_trade + 5.5)["quality"] == "unavailable"


def test_completed_episode_snapshot_cannot_mutate_observer_history():
    feed = recovered()
    feed.event("gap", {"reason": "reconnect"}, feed.at + 0.6)
    state = feed.observer.snapshot()
    state["recent_episodes"][0]["outcome"] = "invented_success"
    assert feed.observer.history[0]["outcome"] == "data_gap"


def test_configuration_rejects_freshness_shorter_than_calculation_period():
    with pytest.raises(ValueError):
        replace(PressureConfig(), sample_s=5, max_age_s=1)


def test_trade_outage_between_calculations_still_revokes_recovery():
    feed = recovered()
    for _ in range(5):
        feed.at += 1
        feed.market.book_at = feed.market.book_exchange_at = feed.at
        feed.event("book", {})
    at = feed.at + 0.8
    feed.event(
        "trades",
        {
            "data": [
                {"i": "new-s", "T": at * 1000, "p": 99.5, "v": 1, "S": "Sell"},
                {"i": "new-b", "T": at * 1000, "p": 99.5, "v": 2, "S": "Buy"},
            ]
        },
        at,
    )
    assert feed.observer.episodes["sell"].state != "recovery"
    assert "Buy" in feed.observer.snapshot()["would_block"]
