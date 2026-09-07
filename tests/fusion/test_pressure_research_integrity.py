"""Research integrity: packet validation and complete reproduction inputs."""

from dataclasses import asdict

from tests.fusion.test_contract_runtime import instrument
from tests.fusion.test_pressure_audit import observations

from capitalizator.fusion.config import Config
from capitalizator.fusion.liquidation_pressure import PressureConfig
from capitalizator.fusion.pressure_labels import label_episodes
from capitalizator.fusion.pressure_research import run
from capitalizator.fusion.store import Store


def test_invalid_packet_tail_cannot_leave_a_successful_barrier_label(tmp_path):
    source = Store(tmp_path / "invalid-tail.sqlite3")
    try:
        source.event(
            1001,
            "BTCUSDT",
            "trades",
            {
                "data": [
                    {"i": "first", "p": 97, "T": 1001000},
                    {"i": "second", "p": 100, "T": "nan"},
                ]
            },
        )
        result = label_episodes(
            source, tmp_path, observations(), {"BTCUSDT": instrument()}, max_age_s=5
        )
        assert result["outcomes"] == {"censored_invalid_trade": 3}
    finally:
        source.close()


def test_study_keeps_full_settings_not_only_irreversible_hashes(tmp_path):
    source = Store(tmp_path / "source.sqlite3")
    try:
        config = Config(symbols=("BTCUSDT",))
        pressure = PressureConfig(minimum_liquidation_usd=123456)
        instruments = {"BTCUSDT": instrument()}
        result = run(source, tmp_path, tmp_path / "study", config, instruments, pressure)
        inputs = result["reproduction"]
        assert inputs["config"] == asdict(config)
        assert inputs["pressure_config"] == asdict(pressure)
        assert inputs["instruments"] == {s: asdict(i) for s, i in instruments.items()}
    finally:
        source.close()


def test_analytics_snapshot_failure_preserves_nonzero_order_path(tmp_path, monkeypatch):
    from tests.fusion.test_liquidation_pressure import (
        test_real_contract_reservation_and_send_identical_off_and_observe as compare_trade,
    )

    from capitalizator.fusion.liquidation_pressure import PressureObserver

    failures = []

    def failed_snapshot(*args, **kwargs):
        failures.append(True)
        raise RuntimeError("controlled analytical snapshot failure")

    monkeypatch.setattr(PressureObserver, "snapshot", failed_snapshot)
    compare_trade(tmp_path, monkeypatch)
    assert failures  # The fault was exercised, not merely installed on an unused path.


def test_replay_closes_database_if_research_engine_initialization_fails(tmp_path, monkeypatch):
    from capitalizator.fusion import replay

    source = Store(tmp_path / "source.sqlite3")
    closed = []
    original_close = Store.close

    def close(store):
        closed.append(store.path)
        original_close(store)

    def failed_engine(*args, **kwargs):
        raise RuntimeError("controlled research initialization failure")

    monkeypatch.setattr(Store, "close", close)
    try:
        import pytest

        output = tmp_path / "failed"
        with pytest.raises(RuntimeError, match="research initialization"):
            replay.compare(
                source,
                tmp_path,
                output,
                Config(symbols=("BTCUSDT",)),
                {"BTCUSDT": instrument()},
                variants=("D",),
                engine_factory=failed_engine,
            )
        assert output / "D.sqlite3" in closed
    finally:
        source.close()
