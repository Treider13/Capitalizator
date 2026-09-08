"""Process-level faults, durable evidence, and the explicit gold-only exception."""

from __future__ import annotations

import inspect
import json
import multiprocessing as mp
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tests.fusion.daily_fixtures import seed_daily
from tests.fusion.test_contract_runtime import account, block, contract, instrument, register
from tests.fusion.test_cross_market import frame

from capitalizator.fusion.atlas import train
from capitalizator.fusion.concurrency import Supervisor
from capitalizator.fusion.config import Config
from capitalizator.fusion.cross_market import entry_check
from capitalizator.fusion.diagnostics import Diagnostics, redact
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store
from capitalizator.fusion.training import TrainingProcess


def test_cleanup_failure_cannot_replace_initiating_failure(tmp_path):
    d = Diagnostics(tmp_path, "policy")
    d.failure("market", RuntimeError("initiating failure"))
    d.failure("shutdown", RuntimeError("secondary cleanup failure"))
    assert Diagnostics(tmp_path, "policy").last_failure["worker"] == "market"
    assert "secondary cleanup failure" in (tmp_path / "logs" / "runtime.jsonl").read_text()


def test_authorization_header_masks_entire_credential():
    assert "SECRET123" not in redact("Authorization: Bearer SECRET123")
    assert "SECRET123" not in redact("{'Authorization': 'Basic SECRET123'}")


def test_forward_audit_never_trains_on_future_labels():
    from capitalizator.fusion.model_audit import audit

    rows = [
        {
            "id": str(i),
            "origin": i * 10.0,
            "available": i * 10.0 + 12,
            "x": [float(i % 3)] * 12,
            "y": [0.0001, 0, 0, 12],
            "context": {"costs": 0.001},
            "symbol": "BTCUSDT",
        }
        for i in range(700)
    ]
    a = audit(rows, Config(), 3)
    assert all(f["train_through"] < f["test_start"] for f in a["folds"])
    changed = [dict(r, y=[99, 0, 0, 12]) if r["origin"] >= 6000 else r for r in rows]
    b = audit(changed, Config(), 3)
    assert a["folds"][0] == b["folds"][0]


@pytest.mark.parametrize("exception", [RuntimeError("injected disk failure"), SystemExit(7)])
def test_worker_failure_is_durable_across_new_runtime(tmp_path, capsys, exception):
    diag = Diagnostics(tmp_path, "policy")
    supervisor = Supervisor(diag.failure)

    def fail():
        raise exception

    supervisor.start("archive", fail)
    supervisor.threads[0].join(2)
    assert supervisor.failed.is_set()
    assert "archive" in supervisor.errors
    saved = Diagnostics(tmp_path, "policy").last_failure
    assert saved["worker"] == "archive"
    assert "Traceback" in saved["traceback"]
    assert saved["run_id"] == diag.run_id
    assert type(exception).__name__ in capsys.readouterr().err
    assert (tmp_path / "logs" / "last_failure.json").stat().st_mode & 0o777 == 0o600


def test_credentials_are_redacted_and_write_failure_does_not_hide_fault(tmp_path, capsys):
    (tmp_path / "logs").write_text("a file blocks directory creation")
    diag = Diagnostics(tmp_path, "policy")
    try:
        raise ValueError("https://provider.test/api?api_key=SECRET123&x=1")
    except ValueError as exc:
        diag.failure("news", exc)
    output = capsys.readouterr().err
    assert "SECRET123" not in output
    assert "[REDACTED]" in output
    assert "diagnostics_write_failed" in output
    assert diag.last_failure["worker"] == "news"


def test_durable_log_rotation_preserves_latest_failure(tmp_path):
    d = Diagnostics(tmp_path, "policy")
    d.failure("trainer", RuntimeError("original"))
    path = tmp_path / "logs" / "runtime.jsonl"
    with path.open("a") as f:
        f.write("x" * 5_000_000)
    d.record("startup")
    assert path.with_name("runtime.jsonl.1").exists()
    assert Diagnostics(tmp_path, "policy").last_failure["error"] == "RuntimeError: original"


def test_real_cli_worker_failure_exits_nonzero_and_survives_restart(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    (tmp_path / "config.json").write_text(json.dumps({"api_port": port}))
    script = """
import sys
import capitalizator.fusion.__main__ as cli
from capitalizator.fusion.runtime import Runtime
class Broken(Runtime):
    def start(self, **kwargs):
        super().start(public=False)
        def fail():
            raise RuntimeError("fault injection: market worker")
        self.supervisor.start("injected-worker", fail)
cli.Runtime = Broken
sys.argv = ["fusion", "--userdir", sys.argv[1]]
raise SystemExit(cli.main())
"""
    root = str(Path(inspect.getfile(Runtime)).resolve().parents[2])
    env = {**os.environ, "PYTHONPATH": root, "OPENBLAS_NUM_THREADS": "1"}
    p = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert p.returncode == 1, p.stderr
    assert "fault injection: market worker" in p.stderr
    saved = json.loads((tmp_path / "logs" / "last_failure.json").read_text())
    assert saved["worker"] == "injected-worker"
    r = Runtime(tmp_path, Config())
    try:
        assert r.status()["last_failure"]["run_id"] == saved["run_id"]
        assert r.status()["run_id"] != saved["run_id"]
    finally:
        r.store.close()


@pytest.mark.parametrize(
    "fault", ["corrupt_database", "invalid_state", "blocked_logs", "data_file"]
)
def test_real_cli_constructor_failure_is_logged_without_runtime(tmp_path, fault):
    root = tmp_path / "data"
    if fault == "data_file":
        root.write_text("cannot create a data directory here")
    else:
        root.mkdir()
        if fault == "invalid_state":
            store = Store(root / "fusion.sqlite3")
            store.put_meta("policy_epoch", "invalid persisted state")
            store.close()
        else:
            (root / "fusion.sqlite3").write_bytes(b"not a SQLite database")
        if fault == "blocked_logs":
            (root / "logs").write_text("diagnostics directory is unavailable")
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(inspect.getfile(Runtime)).resolve().parents[2]),
        "OPENBLAS_NUM_THREADS": "1",
    }
    result = subprocess.run(
        [sys.executable, "-m", "capitalizator.fusion", "--userdir", str(root)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1, result.stderr
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    failures = [r for r in records if r["event"] == "failure"]
    assert len(failures) == 1, result.stderr
    failure = failures[0]
    assert failure["worker"] == "main"
    expected = {"invalid_state": "AttributeError", "data_file": "FileExistsError"}.get(
        fault, "DatabaseError"
    )
    assert failure["error"].startswith(expected + ":")
    assert "Traceback" in failure["traceback"] and "__init__" in failure["traceback"]
    assert records[-1]["event"] == "shutdown"
    assert records[-1]["reason"] == "main_failure" and records[-1]["exit_code"] == 1
    assert records[-1]["run_id"] == failure["run_id"]
    assert "UnboundLocalError" not in result.stderr
    if fault in {"blocked_logs", "data_file"}:
        assert "diagnostics_write_failed" in result.stderr
    else:
        saved = json.loads((root / "logs" / "last_failure.json").read_text())
        assert saved == failure
        journal = [
            json.loads(line) for line in (root / "logs" / "runtime.jsonl").read_text().splitlines()
        ]
        assert journal == records


def test_health_does_not_treat_pause_as_crash_but_detects_worker_failure(tmp_path):
    r = Runtime(tmp_path, Config())
    try:
        r.shared.paused = True
        assert r.health()["healthy"]
        r.supervisor.errors["archive"] = "OSError"
        assert not r.health()["healthy"]
    finally:
        r.store.close()


def test_console_bind_failure_is_durable_and_shutdown_does_not_claim_success(tmp_path, monkeypatch):
    import capitalizator.fusion.__main__ as cli

    def unavailable(*args):
        raise OSError("injected address already in use")

    monkeypatch.setattr(cli.signal, "signal", lambda *args: None)
    monkeypatch.setattr(cli, "server", unavailable)
    monkeypatch.setattr(sys, "argv", ["fusion", "--userdir", str(tmp_path)])
    with pytest.raises(OSError, match="address already in use"):
        cli.main()
    records = [
        json.loads(line) for line in (tmp_path / "logs" / "runtime.jsonl").read_text().splitlines()
    ]
    assert records[-1]["reason"] == "main_failure"
    assert records[-1]["exit_code"] == 1
    assert Diagnostics(tmp_path, Config().version).last_failure["worker"] == "main"


def test_pause_reason_survives_restart(tmp_path):
    r = Runtime(tmp_path, Config())
    r.control("pause", {"paused": True})
    r.store.close()
    r = Runtime(tmp_path, Config())
    try:
        s = r.status()
        assert s["paused"]
        assert s["pause_state"]["reason"] == "operator_pause"
    finally:
        r.store.close()


@pytest.mark.parametrize("symbol,allowed", [("XAUUSDT", True), ("BTCUSDT", False)])
def test_only_gold_can_reserve_without_spot(tmp_path, symbol, allowed):
    store = Store(tmp_path / "db")
    try:
        cfg = Config()
        e = Engine(symbol, store, Shared(), cfg, variant="B")
        e.contract = contract(symbol)
        register(store, e.contract)
        account(store)
        e.market.ingest("book", frame(symbol, qty=2000), 101)
        e.market.ingest("ticker", {"data": {}}, 101)
        seed_daily(e.market)
        e._reserve_entry(block(), None, instrument(symbol), "demo", True, 0.001)
        assert bool(store.rows("SELECT * FROM orders")) == allowed
        assert entry_check(e.market.cross_market(), 1, 101, cfg) == "spot_not_ready"
    finally:
        store.close()


def test_gold_final_dispatch_keeps_linear_generation_time_risk_checks(tmp_path, monkeypatch):
    r = Runtime(tmp_path, Config())
    try:
        c = contract("XAUUSDT")
        register(r.store, c)
        r.shared.broker_ready = True
        r.shared.news_required = False
        r.executor = SimpleNamespace(last_reconcile=101)
        e = r.engines[c.symbol]
        mono = time.monotonic()
        e.market.ingest("book", {**frame(c.symbol), "_received_monotonic": mono}, 101)
        e.market.ingest("ticker", {"data": {}}, 101)
        seed_daily(e.market)
        r.shared.snapshots[c.symbol] = e.market.snapshot()
        monkeypatch.setattr("capitalizator.fusion.runtime.time.time", lambda: 101)
        order = {
            "symbol": c.symbol,
            "mode": "demo",
            "contract": c.id,
            "expires": 110,
            "body": json.dumps({"side": "Buy", "price": "100", "target": "120"}),
        }
        assert r._authorize_send(order)
        # Gold's missing spot generation cannot masquerade as a futures freshness exemption.
        r.spot_faults.add(c.symbol)
        assert r._authorize_send(order)
        e.market.book_exchange_at = 90
        r.shared.snapshots[c.symbol] = e.market.snapshot()
        assert not r._authorize_send(order)
        e.market.book_exchange_at = 101
        r.shared.snapshots[c.symbol] = e.market.snapshot()
        r.shared.paused = True
        assert not r._authorize_send(order)
    finally:
        r.store.close()


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="Linux process-stop fault injection")
def test_training_timeout_covers_full_pipe_and_kills_stopped_child():
    worker = TrainingProcess()
    try:
        os.kill(worker.process.pid, signal.SIGSTOP)
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="during send"):
            worker.fit(
                [{"payload": "x" * 2_000_000}],
                replace(Config(), training_timeout_s=0.2),
                100,
                threading.Event(),
            )
        assert time.monotonic() - started < 4
        assert not worker.process.is_alive()
        assert not worker.io_thread.is_alive()
        with pytest.raises(RuntimeError, match="cannot reuse"):
            worker.fit([], Config(), 100, threading.Event())
    finally:
        worker.close()


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="Linux process-stop fault injection")
def test_shutdown_cancels_training_blocked_in_pipe_send():
    worker = TrainingProcess()
    stop = threading.Event()
    try:
        os.kill(worker.process.pid, signal.SIGSTOP)
        timer = threading.Timer(0.2, stop.set)
        timer.start()
        started = time.monotonic()
        assert worker.fit([{"payload": "x" * 2_000_000}], Config(), 100, stop) is None
        assert time.monotonic() - started < 4
        assert not worker.process.is_alive()
    finally:
        worker.close()
        timer.join(1)


def _send_partial_response(connection):
    connection.recv()
    os.write(connection.fileno(), struct.pack("!i", 100000) + b"partial response")
    os.kill(os.getpid(), signal.SIGSTOP)


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="Linux partial IPC fault injection")
def test_training_timeout_covers_partial_response_not_just_poll(monkeypatch):
    # spawn must import this test target; this path contains tests, not src.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    worker = TrainingProcess()
    worker.process.terminate()
    worker.process.join(2)
    worker.connection.close()
    context = mp.get_context("spawn")
    worker.connection, child = context.Pipe()
    worker.process = context.Process(target=_send_partial_response, args=(child,))
    worker.process.start()
    child.close()
    try:
        with pytest.raises(TimeoutError, match="during receive"):
            worker.fit([], replace(Config(), training_timeout_s=1.5), 100, threading.Event())
        assert not worker.process.is_alive()
        assert not worker.io_thread.is_alive()
    finally:
        worker.close()


def test_unexpected_worker_return_is_fatal_but_shutdown_return_is_normal(tmp_path):
    d = Diagnostics(tmp_path, "policy")
    supervisor = Supervisor(d.failure)
    supervisor.start("market", lambda: None)
    supervisor.threads[0].join(1)
    assert supervisor.failed.is_set()
    assert d.last_failure["worker"] == "market"
    other = Supervisor()
    other.start("market", lambda: other.stop.set())
    other.threads[0].join(1)
    assert not other.failed.is_set()


def test_watchdog_tracks_startup_stalls_and_recovers_only_its_own_halt(tmp_path):
    r = Runtime(tmp_path, Config())
    try:
        r.supervisor.heartbeats["archive"] = time.monotonic() - 200
        r.shared.paused = True
        r.shared.halt("unrelated_incident")
        assert "archive" in r.health()["stale_workers"]
        r._check_workers()
        assert "worker_stale:archive" in r.shared.halts
        lines = (tmp_path / "logs" / "runtime.jsonl").read_text().splitlines()
        record = json.loads(lines[-1])
        assert record["event"] == "watchdog_stale"
        assert record["stacks"]
        r._check_workers()
        assert len((tmp_path / "logs" / "runtime.jsonl").read_text().splitlines()) == len(lines)
        r.supervisor.beat("archive")
        r._check_workers()
        assert "worker_stale:archive" not in r.shared.halts
        assert "unrelated_incident" in r.shared.halts
        assert r.shared.paused
    finally:
        r.store.close()


def test_health_detects_maintenance_and_trainer_stalls_without_waiting_for_maintenance(tmp_path):
    r = Runtime(tmp_path, Config())
    try:
        for name in ("maintenance", "trainer"):
            r.supervisor.heartbeats[name] = time.monotonic() - 1000
        h = r.health()
        assert not h["healthy"]
        assert set(h["stale_workers"]) == {"maintenance", "trainer"}
    finally:
        r.store.close()


def test_nested_stack_diagnostics_redacts_header_values(tmp_path):
    d = Diagnostics(tmp_path, "policy")
    d.record("watchdog_stale", stacks={"worker": "Authorization: Bearer SECRET123"})
    assert "SECRET123" not in (tmp_path / "logs" / "runtime.jsonl").read_text()


def test_training_child_preserves_traceback():
    worker = TrainingProcess()
    try:
        with pytest.raises(RuntimeError, match="Traceback"):
            worker.fit([{}], Config(), 100, threading.Event())
    finally:
        worker.close()


def test_model_report_counts_same_edge_gate_as_runtime():
    rng = np.random.default_rng(9)
    rows = []
    for i in range(700):
        x = rng.normal(size=12)
        rows.append(
            {
                "origin": i * 10.0,
                "available": i * 10.0 + 2,
                "x": x.tolist(),
                "y": [0.001 * x[0] + rng.normal(0, 0.001), 0, 0, 2],
                "context": {"costs": 0.0005},
            }
        )
    m = train(rows, Config(), 10000)
    test = rows[int(len(rows) * 0.8) :]
    admitted = sum(
        any(m.predict(r["x"], 0.1).edge(side, 0.0005) > 0 for side in (1, -1)) for r in test
    )
    assert m.report["signal_count"] == admitted
    assert m.report["abstentions"] == len(test) - admitted
    assert m.report["median_cost_bps"] == 5


def test_no_signal_model_explicitly_fails_without_fabricated_trades():
    rows = [
        {
            "origin": i * 10.0,
            "available": i * 10.0 + 2,
            "x": [0.0] * 12,
            "y": [0.0, 0.0, 0.0, 2.0],
            "context": {"costs": 0.001},
        }
        for i in range(600)
    ]
    m = train(rows, Config(), 10000)
    assert m.report["signal_count"] == 0
    assert "no_cost_covering_signals" in m.report["rejection_reasons"]
    assert not m.report["passed"]
