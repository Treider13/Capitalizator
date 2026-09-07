from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.liquidation_pressure import PressureConfig, PressureObserver
from capitalizator.fusion.store import Store


def settings(**kwargs):
    return replace(
        PressureConfig(),
        warmup_s=120,
        min_baseline_windows=2,
        minimum_liquidation_usd=100,
        minimum_traded_usd=10,
        **kwargs,
    )


class Feed:
    def __init__(self, direction="sell"):
        self.observer = PressureObserver("BTCUSDT", settings())
        self.market = SimpleNamespace(
            valid=True,
            book_at=0,
            book_exchange_at=0,
            bids={float(p): 10.0 for p in range(90, 100)},
            asks={float(p): 10.0 for p in range(101, 111)},
            ticker={},
        )
        self.ident = 0
        self.direction = direction
        self.at = 1000.0

    def event(self, kind, body, at=None):
        self.ident += 1
        return self.observer.step(
            kind, body, self.at if at is None else at, self.market, event_id=self.ident
        )

    def second(self, price=100.0, liquidation=0, sell_qty=1, buy_qty=2):
        self.at += 1
        self.market.book_at = self.market.book_exchange_at = self.at
        self.event("book", {})
        self.event(
            "trades",
            {
                "data": [
                    {
                        "i": f"{self.ident}-s",
                        "T": self.at * 1000,
                        "S": "Sell",
                        "p": price,
                        "v": sell_qty,
                    },
                    {
                        "i": f"{self.ident}-b",
                        "T": self.at * 1000,
                        "S": "Buy",
                        "p": price,
                        "v": buy_qty,
                    },
                ]
            },
        )
        if liquidation:
            self.event(
                "liquidation",
                {
                    "data": [
                        {
                            "s": "BTCUSDT",
                            "S": "Buy" if self.direction == "sell" else "Sell",
                            "T": self.at * 1000,
                            "v": liquidation,
                            "p": "1",
                        }
                    ]
                },
            )
        # Receipt clock is separate from trade count; evaluate the complete packet.
        self.event("pressure_clock", {}, self.at + 0.5)

    def warm(self):
        for _ in range(125):
            self.second()
        assert self.observer.snapshot()["quality"] == "ready"

    def wave(self):
        if self.direction == "sell":
            self.second(99.5, 10, 30, 1)
        else:
            self.second(100.5, 10, 1, 30)
        self.second(99.5 if self.direction == "sell" else 100.5)
        assert self.observer.episodes[self.direction].state == "pressure"


def test_liquidations_remain_separate_and_bankruptcy_price_is_not_used():
    f = Feed()
    f.warm()
    at = f.at + 0.6
    rows = [
        {"s": "BTCUSDT", "S": side, "T": at * 1000, "v": 2, "p": 0.001}
        for side in ("Buy", "Sell", "Buy")
    ]
    f.event("liquidation", {"data": rows}, at)
    bucket = f.observer.buckets[-1]
    assert bucket.long_liquidations == 400
    assert bucket.short_liquidations == 200
    assert not f.observer.episodes  # No directional price/flow confirmation.


def test_repeated_internal_event_is_ignored_but_equal_external_rows_survive():
    f = Feed()
    f.warm()
    stamp = f.at + 0.6
    frame = {"data": [{"s": "BTCUSDT", "S": "Buy", "T": stamp * 1000, "v": 2}]}
    f.event("liquidation", frame, stamp)
    f.observer.step("liquidation", frame, stamp, f.market, event_id=f.ident)
    assert f.observer.buckets[-1].long_liquidations == 200
    f.event("liquidation", frame, stamp)
    assert f.observer.buckets[-1].long_liquidations == 400


@pytest.mark.parametrize("direction", ["sell", "buy"])
def test_wave_then_independent_flow_confirms_recovery(direction):
    f = Feed(direction)
    f.warm()
    f.wave()
    price = 99.5 if direction == "sell" else 100.5
    for _ in range(48):
        f.second(price)
    ep = f.observer.episodes[direction]
    assert ep.state == "recovery"
    assert ep.checking_since > ep.started
    assert f.observer.snapshot()["affects_orders"] is False
    assert ("Buy" if direction == "sell" else "Sell") not in f.observer.snapshot()["would_block"]


def test_second_wave_revokes_recovery():
    f = Feed()
    f.warm()
    f.wave()
    for _ in range(48):
        f.second(99.5)
    assert f.observer.episodes["sell"].state == "recovery"
    f.second(98, 20, 50, 1)
    f.second(98)
    assert f.observer.episodes["sell"].state == "pressure"
    assert "Buy" in f.observer.snapshot()["would_block"]


def test_no_trades_or_liquidation_silence_cannot_confirm():
    f = Feed()
    f.warm()
    f.wave()
    for _ in range(130):
        f.at += 1
        f.market.book_at = f.market.book_exchange_at = f.at
        f.event("book", {})
    assert f.observer.episodes["sell"].state == "mixed"
    assert "Buy" in f.observer.snapshot()["would_block"]


def test_unobservable_fixed_depth_band_cannot_confirm():
    f = Feed()
    f.warm()
    f.wave()
    for _ in range(34):
        f.second(99.5)
    f.market.bids = {99.0: 1000.0}  # Huge quote, but old band is not observable.
    for _ in range(20):
        f.second(99.5)
    assert f.observer.episodes["sell"].state != "recovery"


def test_gap_discards_warmup_and_censors_active_episode():
    f = Feed()
    f.warm()
    f.wave()
    f.event("gap", {"reason": "feed_generation"}, f.at + 0.6)
    snapshot = f.observer.snapshot()
    assert snapshot["quality"] == "unavailable"
    assert snapshot["would_block"] == ["Buy", "Sell"]
    assert snapshot["recent_episodes"][-1]["outcome"] == "data_gap"
    assert not f.observer.baseline
    f.second()
    assert f.observer.snapshot()["quality"] == "warming"


def test_stale_book_and_late_liquidation_are_not_zero_pressure():
    f = Feed()
    f.warm()
    f.event("pressure_clock", {}, f.at + 10)
    assert f.observer.snapshot()["quality"] == "unavailable"
    f.second()  # clock regression cannot produce ready state
    assert f.observer.snapshot()["quality"] != "ready"
    f = Feed()
    f.warm()
    f.event("liquidation", {"data": [{"s": "BTCUSDT", "S": "Buy", "T": 1000, "v": 1}]}, f.at + 0.6)
    assert f.observer.snapshot()["reason"] == "late_liquidation"


def test_memory_is_bounded_and_snapshot_json_is_finite():
    f = Feed()
    for _ in range(2000):
        f.second()
    assert len(f.observer.buckets) <= 121
    assert len(f.observer.baseline) <= f.observer.config.baseline_windows
    json.dumps(f.observer.snapshot(), allow_nan=False)


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "filter"},
        {"warmup_s": 0},
        {"sample_s": 0.01},
        {"baseline_windows": True},
        {"movement_bps": float("nan")},
        {"symbols": ("SOLUSDT",)},
        {"confirmation_s": 200},
    ],
)
def test_invalid_or_trading_configuration_is_rejected(change):
    with pytest.raises(ValueError):
        replace(PressureConfig(), **change)


def test_analytics_config_does_not_change_trading_policy_version():
    baseline = Config().version
    replace(PressureConfig(), mode="off")
    assert Config().version == baseline


def test_observer_exception_does_not_halt_or_mutate_contract(tmp_path, monkeypatch):
    store = Store(tmp_path / "observer.sqlite3")
    try:
        shared = Shared()
        engine = Engine("BTCUSDT", store, shared, Config())

        def broken(*args, **kwargs):
            raise ValueError("controlled observer failure")

        monkeypatch.setattr(engine.pressure, "step", broken)
        engine.process("pressure_clock", {}, 1000)
        assert not shared.halted
        assert engine.contract is None
        assert not store.rows("SELECT * FROM orders")
        assert shared.snapshots["BTCUSDT"]["liquidation_pressure"]["quality"] == "error"
    finally:
        store.close()


def test_real_contract_reservation_and_send_identical_off_and_observe(tmp_path, monkeypatch):
    from tests.fusion import test_integration as scenario

    original = scenario.Engine
    outputs = []
    for mode in ("off", "observe"):

        class SelectedEngine(original):
            def __init__(self, *args, **kwargs):
                super().__init__(
                    *args, **kwargs, pressure_config=replace(PressureConfig(), mode=mode)
                )

        monkeypatch.setattr(scenario, "Engine", SelectedEngine)
        store = Store(tmp_path / (mode + ".sqlite3"))
        try:
            cfg = Config(
                symbols=("BTCUSDT", "ETHUSDT"),
                context_blocks=4,
                block_trades=2,
                block_seconds=0.001,
                horizon_blocks=2,
                demo_samples=32,
                live_samples=128,
                retrain_samples=16,
            )
            scenario.test_candidate_new_reaction_risk_reservation_and_venue_send(store, cfg)
            outputs.append(
                {
                    table: store.rows(f"SELECT * FROM {table}")
                    for table in ("orders", "contracts", "samples", "models", "commands")
                }
            )
            assert store.rows("SELECT * FROM orders WHERE state='accepted'")
        finally:
            store.close()
    assert outputs[0] == outputs[1]


def test_raw_event_learning_and_replay_off_observe_parity(tmp_path):
    from tests.fusion.test_contract_runtime import instrument, trade_frame

    from capitalizator.fusion.replay import compare

    cfg = Config(
        symbols=("BTCUSDT",),
        block_trades=2,
        block_seconds=0.001,
        context_blocks=4,
        horizon_blocks=2,
        demo_samples=32,
        live_samples=128,
    )
    source = Store(tmp_path / "source.sqlite3")
    try:
        for i in range(40):
            at = 1000 + i
            source.event(
                at,
                "BTCUSDT",
                "book",
                {
                    "type": "snapshot" if i == 0 else "delta",
                    "ts": at * 1000,
                    "data": {"u": i + 1, "b": [["99", "100"]], "a": [["101", "100"]]},
                },
            )
            source.event(at, "BTCUSDT", "trades", trade_frame(i, 100 + (i % 3) * 0.01, at))
            source.event(at + 0.5, "BTCUSDT", "pressure_clock", {})
        results = []
        tables = []
        for mode in ("off", "observe"):
            results.append(
                compare(
                    source,
                    tmp_path,
                    tmp_path / mode,
                    cfg,
                    {"BTCUSDT": instrument()},
                    pressure_config=replace(PressureConfig(), mode=mode),
                )
            )
            store = Store(tmp_path / mode / "D.sqlite3")
            try:
                tables.append(
                    {
                        table: store.rows(f"SELECT * FROM {table}")
                        for table in ("samples", "orders", "contracts", "models")
                    }
                )
                assert tables[-1]["samples"]
            finally:
                store.close()
        assert results[0] == results[1]
        assert tables[0] == tables[1]
    finally:
        source.close()


def test_research_freezes_input_and_reports_insufficient_evidence(tmp_path):
    from tests.fusion.test_contract_runtime import instrument

    from capitalizator.fusion.pressure_research import run

    source = Store(tmp_path / "source.sqlite3")
    try:
        cfg = Config(symbols=("BTCUSDT",))
        output = tmp_path / "research"
        result = run(source, tmp_path, output, cfg, {"BTCUSDT": instrument()}, PressureConfig())
        assert result["status"] == "insufficient_evidence"
        assert result["promotion_allowed"] is False
        assert result["input_events"] == 0
        assert set(result["results"]) == {"baseline", "pause", "detector"}
        assert (output / "input.sqlite3").is_file()
        with pytest.raises(ValueError, match="new directory"):
            run(source, tmp_path, output, cfg, {"BTCUSDT": instrument()}, PressureConfig())
    finally:
        source.close()


def test_research_policies_have_real_separate_vetoes(tmp_path, monkeypatch):
    from tests.fusion.test_contract_runtime import block, contract, instrument

    from capitalizator.fusion.pressure_research import ResearchEngine

    sent = []
    monkeypatch.setattr(Engine, "_send", lambda *args: sent.append(args[0].research_policy))
    store = Store(tmp_path / "research.sqlite3")
    try:
        for policy in ("baseline", "pause", "detector"):
            engine = ResearchEngine("BTCUSDT", store, Shared(), Config(), research_policy=policy)
            engine.contract = contract()
            monkeypatch.setattr(
                engine.pressure,
                "snapshot",
                lambda *args: {
                    "quality": "ready",
                    "would_block": ["Buy"],
                    "episodes": [{"direction": "sell", "last_wave": 100}],
                    "recent_episodes": [],
                },
            )
            engine._send(block(), None, instrument(), "demo", True, 0)
        assert sent == ["baseline"]
        rows = [json.loads(r["body"]) for r in store.rows("SELECT * FROM decisions")]
        assert [r["would_veto"] for r in rows] == [None, "fixed_pause", "pressure_detector"]
    finally:
        store.close()


def test_stale_evaluation_cannot_be_refreshed_by_spot_traffic():
    feed = Feed()
    feed.warm()
    evaluated = feed.observer.last_eval
    feed.event("spot_book", {}, evaluated + 10)
    assert feed.observer.snapshot(evaluated + 10)["quality"] == "unavailable"
    assert feed.observer.snapshot(evaluated + 10)["would_block"] == ["Buy", "Sell"]


def test_no_recent_trades_is_unknown_even_with_fresh_book():
    feed = Feed()
    feed.warm()
    for _ in range(10):
        feed.at += 1
        feed.market.book_at = feed.market.book_exchange_at = feed.at
        feed.event("book", {})
    assert feed.observer.snapshot()["quality"] == "unavailable"
    assert feed.observer.reason == "insufficient_recent_trades"


def test_configuration_error_survives_reconnect():
    feed = Feed()
    feed.observer.fail(ValueError("invalid config"))
    feed.observer.configuration_error = feed.observer.error
    feed.event("gap", {"reason": "reconnect"})
    assert feed.observer.snapshot()["quality"] == "error"
    feed.second()
    assert feed.observer.snapshot()["quality"] == "error"


def test_snapshot_is_detached_from_internal_metrics():
    feed = Feed()
    feed.warm()
    snapshot = feed.observer.snapshot()
    snapshot["metrics"]["windows"]["5"]["buy_usd"] = -1
    assert feed.observer.metrics["windows"]["5"]["buy_usd"] >= 0


def test_offline_labels_first_barrier_and_gap_censoring(tmp_path):
    from capitalizator.fusion.pressure_labels import label_episodes
    from capitalizator.fusion.risk import Instrument

    instrument = Instrument("BTCUSDT", 0.1, 0.001, 0.001, 1, 100, 100, 0.0002, 0.00055, 480)
    observations = [
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
    source = Store(tmp_path / "labels.sqlite3")
    try:
        source.event(1001, "BTCUSDT", "trades", {"data": [{"p": 97, "T": 1001000}]})
        result = label_episodes(
            source, tmp_path, observations, {"BTCUSDT": instrument}, max_age_s=5
        )
        assert result["distinct_episodes"] == 1
        assert result["outcomes"] == {"continuation_first": 3}
        source.event(1002, "BTCUSDT", "gap", {})
        result = label_episodes(
            source, tmp_path, observations, {"BTCUSDT": instrument}, max_age_s=5
        )
        assert result["outcomes"] == {
            "continuation_first": 3
        }  # later gap cannot change known first hit
        observations[0]["at"] = 1001
        result = label_episodes(
            source, tmp_path, observations, {"BTCUSDT": instrument}, max_age_s=5
        )
        assert result["outcomes"] == {"censored_data_gap": 3}
    finally:
        source.close()


def test_snapshot_failure_does_not_escape_into_trading_engine(tmp_path, monkeypatch):
    store = Store(tmp_path / "snapshot-failure.sqlite3")
    try:
        shared = Shared()
        engine = Engine("BTCUSDT", store, shared, Config())

        def broken(*args, **kwargs):
            raise RuntimeError("snapshot fault")

        monkeypatch.setattr(engine.pressure, "snapshot", broken)
        engine.process("pressure_clock", {}, 1000)
        assert not shared.halted
        assert shared.snapshots["BTCUSDT"]["liquidation_pressure"]["quality"] == "error"
    finally:
        store.close()


def test_disappearing_depth_revokes_existing_recovery():
    feed = Feed()
    feed.warm()
    feed.wave()
    for _ in range(48):
        feed.second(99.5)
    assert feed.observer.episodes["sell"].state == "recovery"
    feed.market.bids = {99.0: 1000.0}
    feed.second(99.5)
    assert feed.observer.episodes["sell"].state == "mixed"
    assert "Buy" in feed.observer.snapshot()["would_block"]


def test_trade_clock_regression_censors_instead_of_silently_dropping_volume():
    feed = Feed()
    feed.warm()
    feed.event(
        "trades",
        {"data": [{"i": "regressed", "T": (feed.at - 1) * 1000, "S": "Sell", "p": 100, "v": 1}]},
        feed.at + 0.6,
    )
    assert feed.observer.snapshot()["reason"] == "trade_clock_regressed"
    assert feed.observer.snapshot()["quality"] == "unavailable"


def test_unobserved_interval_forces_new_baseline_even_if_latest_book_is_fresh():
    feed = Feed()
    feed.warm()
    feed.at += 20
    feed.second()
    assert feed.observer.snapshot()["quality"] == "warming"
    assert not feed.observer.baseline
