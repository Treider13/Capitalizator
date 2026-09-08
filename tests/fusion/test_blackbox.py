"""Operator UI regressions: real HTTP assets, journal boundaries and read-only access."""

from __future__ import annotations

import json
import shlex
import threading
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from capitalizator.fusion.config import Config
from capitalizator.fusion.console_records import records
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store
from capitalizator.fusion.web import ASSETS, server


def test_journal_pages_are_complete_and_mode_isolated(tmp_path):
    store = Store(tmp_path / "db")
    try:
        for i in range(53):
            store.decision(float(i), "BTCUSDT", "check", {"i": i})
        seen, before = [], None
        while True:
            page = records(store, "demo", "decisions", 20, before)
            seen.extend(json.loads(r["body"])["i"] for r in page["rows"])
            before = page["next_before"]
            if before is None:
                break
        assert seen == list(reversed(range(53)))
        for mode in ("demo", "live"):
            store.command(mode, mode, "BTCUSDT", "stop", 100, {"mode": mode})
        assert [r["id"] for r in records(store, "demo", "commands")["rows"]] == ["demo"]
        assert [r["id"] for r in records(store, "live", "commands")["rows"]] == ["live"]
        store.put_meta("secret:sentinel", {"key": "must-not-leak"})
        store.put_meta("archive:test", {"path": "test.parquet"})
        page = records(store, "demo", "archives")
        assert [r["key"] for r in page["rows"]] == ["archive:test"]
        assert "must-not-leak" not in json.dumps(page)
    finally:
        store.close()


@pytest.mark.parametrize(
    "kind,limit,before",
    [
        ("meta", 20, None),
        ("orders; DROP TABLE orders", 20, None),
        ("decisions", 0, None),
        ("decisions", 51, None),
        ("decisions", True, None),
        ("decisions", 20, -1),
        ("decisions", 20, 2**63),
        ("decisions", 20, True),
    ],
)
def test_journal_rejects_unbounded_or_arbitrary_queries(tmp_path, kind, limit, before):
    store = Store(tmp_path / "db")
    try:
        with pytest.raises(ValueError):
            records(store, "demo", kind, limit, before)
        assert store.rows("SELECT * FROM orders") == []
    finally:
        store.close()


def test_blackbox_http_assets_records_and_host_guards(tmp_path):
    runtime = Runtime(tmp_path, Config())
    runtime.store.decision(100, "BTCUSDT", "reason", {"text": "<script>alert(1)</script>"})
    http = server(runtime, 0)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{http.server_port}"
    try:
        with urlopen(url, timeout=3) as response:
            page = response.read().decode()
        assert "BLACKBOX" in page and "__TOKEN__" not in page
        for asset, (content, mime) in ASSETS.items():
            with urlopen(url + asset, timeout=3) as response:
                assert response.read() == content
                assert response.headers["Content-Type"] == mime
                assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urlopen(url + "/api/records?kind=decisions&limit=1", timeout=3) as response:
            assert json.load(response)["rows"][0]["symbol"] == "BTCUSDT"
        for path, code in [
            ("/api/records?kind=meta", 400),
            ("/api/records?kind=events&limit=99999999", 400),
            ("/api/records?kind=orders&before=nan", 400),
            ("/assets/../runtime.py", 404),
            ("/assets/secrets.json", 404),
        ]:
            with pytest.raises(HTTPError) as error:
                urlopen(url + path, timeout=3)
            assert error.value.code == code
        for path in ["/assets/dashboard.js", "/api/records?kind=orders"]:
            with pytest.raises(HTTPError) as error:
                urlopen(Request(url + path, headers={"Host": "attacker.example"}), timeout=3)
            assert error.value.code == 403
        assert runtime.store.rows("SELECT * FROM commands") == []
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)
        runtime.close()
    assert not thread.is_alive()


def test_maintenance_commands_use_actual_quoted_paths_and_do_not_execute(tmp_path):
    root = tmp_path / "a space and ' quote"
    root.mkdir()
    config_path = root / "custom config.json"
    config_path.write_text(json.dumps({"leverage": 3.0}))
    runtime = Runtime(root, Config.load(config_path), config_path=config_path)
    try:
        commands = runtime.maintenance_commands()["commands"]
        replay = shlex.split(commands[1])
        assert replay[replay.index("--userdir") + 1] == str(root)
        assert replay[replay.index("--config") + 1] == str(config_path)
        assert not (tmp_path / (root.name + "-replay")).exists()
        status = runtime.status()
        assert status["active_model_report"] is None
        assert status["maintenance"] == runtime.maintenance_commands()
        assert runtime.store.rows("SELECT * FROM commands") == []
    finally:
        runtime.close()


@pytest.mark.parametrize("table", ["orders", "commands", "executions"])
def test_account_journal_does_not_sort_entire_history(tmp_path, table):
    store = Store(tmp_path / "db")
    try:
        plan = store.rows(
            f"EXPLAIN QUERY PLAN SELECT rowid AS cursor,* FROM {table} "
            "WHERE mode=? ORDER BY rowid DESC LIMIT ?",
            ("demo", 21),
        )
        assert all("TEMP B-TREE" not in r["detail"] for r in plan)
        assert any("USING INDEX console_" in r["detail"] for r in plan)
    finally:
        store.close()


def test_journals_read_committed_state_without_waiting_for_trade_writer(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = Store(tmp_path / "db")
    try:
        store.decision(100, "BTCUSDT", "committed", {})
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store.transaction() as db:
                db.execute(
                    "INSERT INTO decisions(at,symbol,kind,body) VALUES(101,'BTCUSDT','new','{}')"
                )
                # A Store.rows reader would wait on this transaction's Python lock.
                future = pool.submit(records, store, "demo", "decisions")
                page = future.result(timeout=2)
                assert [r["kind"] for r in page["rows"]] == ["committed"]
        assert len(records(store, "demo", "decisions")["rows"]) == 2
    finally:
        store.close()


def test_all_stored_headlines_samples_and_dispatch_errors_are_visible(tmp_path):
    store = Store(tmp_path / "db")
    try:
        for i in range(45):
            store.put_meta(f"news_item:{i}", {"title": str(i), "published": i})
        store.put_meta("secret:test", {"key": "excluded"})
        ids, before = [], None
        while True:
            page = records(store, "demo", "headlines", 20, before)
            ids.extend(r["key"] for r in page["rows"])
            before = page["next_before"]
            if before is None:
                break
        assert len(set(ids)) == 45 and all(k.startswith("news_item:") for k in ids)
        store.sample("sample1", "BTCUSDT", 100, 110, [1.0], [2.0], {"policy": "test"})
        assert records(store, "demo", "samples")["rows"][0]["id"] == "sample1"
        for mode in ("demo", "live"):
            store.command(mode, mode, "BTCUSDT", "flatten", 100, {})
            with store.transaction() as db:
                db.execute(
                    "INSERT INTO dispatch VALUES('command',?,100,105,'TimeoutError')", (mode,)
                )
        page = records(store, "demo", "dispatch")
        assert [r["id"] for r in page["rows"]] == ["demo"]
        assert page["rows"][0]["error"] == "TimeoutError"
        assert page["rows"][0]["next_at"] == 105
    finally:
        store.close()


def test_corrupt_console_records_are_reported_without_losing_other_data(tmp_path):
    runtime = Runtime(tmp_path, Config())
    try:
        runtime.store.account("demo", 100, 1000, [], [], "2026-09-06")
        with runtime.store.transaction() as db:
            db.execute("UPDATE account SET body='{broken'")
            db.execute("INSERT INTO executions VALUES('demo','bad','bad','BTCUSDT',100,'{broken')")
            db.execute(
                "INSERT INTO contracts VALUES('bad','BTCUSDT',100,'observing','{broken',100)"
            )
        data = runtime.chart("BTCUSDT", "1m")
        assert {e["source"] for e in data["data_errors"]} == {"account", "executions", "contracts"}
        assert data["candles"] == []
        assert data["positions"] == []
        status = runtime.status()
        assert status["config"]["symbols"] == Config().symbols
        assert status["performance"]["error"]
        assert status["account"]["body"] == "{broken"
        assert records(runtime.store, "demo", "executions")["rows"][0]["body"] == "{broken"
    finally:
        runtime.close()


def test_chart_checks_use_server_monotonic_receipt_age(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, Config())
    try:
        book = {
            "valid": True,
            "book_at": 100,
            "exchange_at": 100,
            "received_monotonic": 10,
            "spread_bps": 1,
            "imbalance": 0,
        }
        runtime.shared.snapshots["BTCUSDT"] = {
            "cross_market": {"linear": book, "spot": {**book, "status": "streaming"}}
        }
        monkeypatch.setattr("capitalizator.fusion.runtime.time.time", lambda: 101)
        monkeypatch.setattr("capitalizator.fusion.runtime.time.monotonic", lambda: 20)
        data = runtime.chart("BTCUSDT", "1m")
        assert data["book_entry_checks"]["Buy"] == "spot_stale_elapsed"
        assert data["monotonic_at"] == 20
    finally:
        runtime.store.close()


def test_real_runtime_payload_renders_in_console_model(tmp_path):
    import os
    import shutil
    import subprocess
    import time

    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for server-to-console contract integration")
    runtime = Runtime(tmp_path / "runtime", Config())
    try:
        engine = runtime.engines["BTCUSDT"]
        now = time.time()
        engine.process(
            "history",
            {
                "tf": "1m",
                "rows": [[str(int(now // 60 - 1) * 60000), "100", "102", "99", "101", "10"]],
            },
            now,
        )
        # Engine publishes production snapshot structures; no manually invented API schema.
        payload = {"status": runtime.status(), "chart": runtime.chart("BTCUSDT", "1m")}
        path = tmp_path / "runtime-payload.json"
        path.write_text(json.dumps(payload))
        result = subprocess.run(
            [node, str(Path(__file__).resolve().parents[2] / "tools/check_fusion_dashboard.cjs")],
            env={
                **os.environ,
                "BLACKBOX_RUNTIME_PAYLOAD": str(path),
                "BLACKBOX_FUSION_ROOT": str(files("capitalizator.fusion")),
            },
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert '"runtime_contract":"passed"' in result.stdout
    finally:
        runtime.close()
