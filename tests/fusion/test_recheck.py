"""Reproduced failures found after the six-pair acceptance run."""

import sys
from io import BytesIO

import pytest
from tests.fusion.test_contract_runtime import FakeVenue, pending

from capitalizator.fusion.__main__ import main
from capitalizator.fusion.config import Config
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.store import Store


@pytest.mark.parametrize("directory", [False, True])
def test_explicit_invalid_config_never_falls_back_to_default(tmp_path, monkeypatch, directory):
    path = tmp_path / "requested.json"
    if directory:
        path.mkdir()
    monkeypatch.setattr(
        sys, "argv", ["fusion", "--userdir", str(tmp_path), "--config", str(path), "--status"]
    )

    def unexpected_request(*args, **kwargs):
        pytest.fail("invalid explicit config reached HTTP using default settings")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_request)
    with pytest.raises(OSError):
        main()


@pytest.mark.parametrize("local_file", [False, True])
def test_default_config_bootstrap_and_existing_local_config(tmp_path, monkeypatch, local_file):
    if local_file:
        (tmp_path / "config.json").write_text('{"api_port": 9082}')
    monkeypatch.setattr(sys, "argv", ["fusion", "--userdir", str(tmp_path), "--status"])
    seen = []

    def status_request(url, **kwargs):
        seen.append(url)
        return BytesIO(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", status_request)
    main()
    port = 9082 if local_file else Config().api_port
    assert seen == [f"http://127.0.0.1:{port}/api/status"]


def test_late_position_after_terminal_cancel_retains_exit_intent(tmp_path):
    store = Store(tmp_path / "db")
    try:
        cfg = Config()
        pending(store, cfg)
        venue = FakeVenue()
        executor = Executor(store, venue, cfg)
        executor.tick(102, True)
        store.command("operator-close", "demo", "BTCUSDT", "flatten", 103, {})
        executor.tick(103, False)
        executor.reconcile(104)
        executor.tick(104, False)
        assert (
            store.rows("SELECT state FROM commands WHERE id='operator-close'")[0]["state"] == "done"
        )
        assert not venue.closes
        # The cancel is terminal; the position snapshot reflecting its partial
        # execution arrives later on an independent account stream.
        venue.positions = [
            {
                "symbol": "BTCUSDT",
                "side": "Buy",
                "size": "0.007",
                "avgPrice": "100",
                "markPrice": "100",
                "stopLoss": "95",
            }
        ]
        executor.reconcile(105)
        executor.tick(105, False)
        assert venue.closes, "late position survived a completed operator close"
        assert venue.closes[0][0]["size"] == "0.007"
        assert store.rows("SELECT state FROM contracts")[0]["state"] == "refuted"
    finally:
        store.close()
