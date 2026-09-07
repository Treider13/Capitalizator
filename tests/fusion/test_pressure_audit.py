"""Adversarial regressions from the second liquidation-observer audit."""

import json

from tests.fusion.test_contract_runtime import contract, instrument
from tests.fusion.test_liquidation_pressure import Feed

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.pressure_labels import label_episodes
from capitalizator.fusion.store import Store


def test_analytical_timer_never_applies_pending_instrument_change(tmp_path):
    store = Store(tmp_path / "clock.sqlite3")
    try:
        shared = Shared()
        engine = Engine("BTCUSDT", store, shared, Config())
        engine.contract = contract()
        engine.contract_state = "confirmed"
        engine.market.tick = 0.5
        shared.instruments["BTCUSDT"] = instrument()
        engine.process("pressure_clock", {}, 1000)
        assert engine.market.tick == 0.5
        assert engine.contract_state == "confirmed"
        assert not store.rows("SELECT * FROM events WHERE kind='gap'")
    finally:
        store.close()


def test_spot_receipt_regression_cannot_reset_futures_observation():
    feed = Feed()
    feed.warm()
    generation = feed.observer.generation
    feed.event("spot_book", {}, feed.at - 1)
    assert feed.observer.generation == generation
    assert feed.observer.snapshot()["quality"] == "ready"


def test_transient_depth_loss_restarts_confirmation():
    feed = Feed()
    feed.warm()
    feed.wave()
    for _ in range(36):
        feed.second(99.5)
    ep = feed.observer.episodes["sell"]
    assert ep.checking_since is not None
    before = ep.checking_since
    original = feed.market.bids.copy()
    feed.market.bids = {p: q * 0.01 for p, q in original.items()}
    feed.second(99.5)
    feed.market.bids = original
    feed.second(99.5)
    assert ep.checking_since is not None and ep.checking_since > before
    assert ep.state != "recovery"


def observations():
    return [
        {
            "at": 1000,
            "symbol": "BTCUSDT",
            "body": json.dumps(
                {
                    "quality": "ready",
                    "episodes": [{"id": "one", "state": "pressure", "direction": "sell"}],
                    "metrics": {"windows": {"120": {"last": 100, "low": 99, "high": 101}}},
                }
            ),
        }
    ]


def test_other_actor_cannot_activate_signal_before_its_own_time(tmp_path):
    store = Store(tmp_path / "interleaving.sqlite3")
    try:
        store.event(1001, "ETHUSDT", "book", {})
        store.event(999, "BTCUSDT", "gap", {})
        store.event(1002, "BTCUSDT", "trades", {"data": [{"i": "a", "p": 97, "T": 1002000}]})
        result = label_episodes(
            store, tmp_path, observations(), {"BTCUSDT": instrument()}, max_age_s=5
        )
        assert result["outcomes"] == {"continuation_first": 3}
    finally:
        store.close()


def test_empty_trade_packets_cannot_prove_future_continuity(tmp_path):
    store = Store(tmp_path / "empty.sqlite3")
    try:
        for at in range(1001, 1062):
            store.event(at, "BTCUSDT", "trades", {"data": []})
        result = label_episodes(
            store, tmp_path, observations(), {"BTCUSDT": instrument()}, max_age_s=5
        )
        assert "neither_barrier" not in result["outcomes"]
    finally:
        store.close()


def test_quote_flash_between_calculations_invalidates_confirmation():
    feed = Feed()
    feed.warm()
    feed.wave()
    for _ in range(36):
        feed.second(99.5)
    ep = feed.observer.episodes["sell"]
    assert ep.checking_since is not None
    evaluated = feed.observer.last_eval
    original = feed.market.bids.copy()
    feed.market.bids = {p: q * 0.01 for p, q in original.items()}
    feed.event("book", {}, evaluated + 0.1)
    feed.market.bids = original
    feed.event("book", {}, evaluated + 0.2)
    assert feed.observer.last_eval == evaluated
    assert ep.checking_since is None
    assert ep.state == "mixed"


def test_delayed_timer_cannot_reset_newer_market_data():
    feed = Feed()
    feed.warm()
    generation = feed.observer.generation
    feed.event("pressure_clock", {}, feed.at - 0.1)
    assert feed.observer.generation == generation
    assert feed.observer.snapshot()["quality"] == "ready"


def test_idle_timer_then_queued_earlier_receipt_does_not_create_second_gap():
    feed = Feed()
    feed.warm()
    feed.event("pressure_clock", {}, feed.at + 6)
    generation = feed.observer.generation
    # The callback arrived just before the timer but was enqueued just after get().
    feed.at += 5.99
    feed.market.book_at = feed.market.book_exchange_at = feed.at
    feed.event("book", {})
    assert feed.observer.generation == generation
    assert feed.observer.reason == "collecting_baseline"


def test_repeated_trade_does_not_reappear_as_a_future_barrier_hit(tmp_path):
    store = Store(tmp_path / "duplicate.sqlite3")
    try:
        trade = {"i": "same", "p": 97, "T": 999000}
        store.event(999, "BTCUSDT", "trades", {"data": [trade]})
        store.event(1001, "BTCUSDT", "trades", {"data": [trade]})
        result = label_episodes(
            store, tmp_path, observations(), {"BTCUSDT": instrument()}, max_age_s=5
        )
        assert result["outcomes"] == {"censored_end_of_recording": 3}
    finally:
        store.close()


def test_regressed_symbol_tape_cannot_turn_predecision_price_into_success(tmp_path):
    store = Store(tmp_path / "regressed.sqlite3")
    try:
        store.event(1001, "BTCUSDT", "trades", {"data": [{"i": "a", "p": 97, "T": 1001000}]})
        store.event(999, "BTCUSDT", "book", {})
        result = label_episodes(
            store, tmp_path, observations(), {"BTCUSDT": instrument()}, max_age_s=5
        )
        assert result["outcomes"] == {"censored_receipt_order": 3}
        assert result["receipt_order_rejected_symbols"] == ["BTCUSDT"]
    finally:
        store.close()
