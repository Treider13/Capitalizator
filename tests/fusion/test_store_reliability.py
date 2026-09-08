"""SQLite faults and recovery against real files, transactions and processes."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import capitalizator.fusion.store as storage
from capitalizator.fusion.archive import archive_events, events
from capitalizator.fusion.backup import backup
from capitalizator.fusion.store import Store


def test_sqlite_full_preserves_original_error_and_connection_recovers(tmp_path):
    store = Store(tmp_path / "db")
    try:
        store.put_meta("committed", 1)
        pages = store.db.execute("PRAGMA page_count").fetchone()[0]
        store.db.execute(f"PRAGMA max_page_count={pages + 1}")
        with pytest.raises(sqlite3.OperationalError) as caught:
            with store.transaction() as db:
                db.execute("INSERT INTO meta VALUES('uncommitted','1')")
                db.execute("INSERT INTO meta VALUES('oversized',zeroblob(1048576))")
        assert caught.value.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert store.meta("committed") == 1 and store.meta("uncommitted") is None
        assert not store.db.in_transaction
        store.put_meta("after_failure", 2)
        assert store.meta("after_failure") == 2
    finally:
        store.close()


def test_sqlite_automatic_constraint_rollback_keeps_integrity_error(tmp_path):
    store = Store(tmp_path / "db")
    try:
        store.put_meta("existing", 1)
        with pytest.raises(sqlite3.IntegrityError):
            with store.transaction() as db:
                db.execute("INSERT OR ROLLBACK INTO meta VALUES('existing','2')")
        assert store.meta("existing") == 1
    finally:
        store.close()


def test_failed_rollback_preserves_cause_and_closes_unusable_connection(tmp_path):
    store = Store(tmp_path / "db")
    store.db.set_authorizer(
        lambda action, name, *_: sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_TRANSACTION and name == "ROLLBACK"
        else sqlite3.SQLITE_OK
    )
    try:
        with pytest.raises(RuntimeError, match="initiating failure") as caught:
            with store.transaction() as db:
                db.execute("INSERT INTO meta VALUES('uncommitted','1')")
                raise RuntimeError("initiating failure")
        assert any("rollback failed" in note for note in caught.value.__notes__)
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            store.db.execute("SELECT 1")
        reopened = Store(tmp_path / "db")
        try:
            assert reopened.meta("uncommitted") is None
        finally:
            reopened.close()
    finally:
        store.close()


def track_connections(monkeypatch):
    connections = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        connections.append(db)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    return connections


def test_schema_failure_rolls_back_all_ddl_and_closes_connection(tmp_path, monkeypatch):
    connections = track_connections(monkeypatch)
    path = tmp_path / "db"
    monkeypatch.setattr(
        storage, "SCHEMA", storage.SCHEMA + "\nCREATE INDEX bad ON missing_table(x);\n"
    )
    try:
        with pytest.raises(sqlite3.OperationalError, match="missing_table"):
            Store(path)
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
        db = sqlite3.connect(path)
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        for db in connections:
            db.close()


def test_future_schema_is_rejected_before_modifying_database(tmp_path):
    path = tmp_path / "db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=999")
    db.close()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="schema version"):
        Store(path)
    assert path.read_bytes() == before


def test_legacy_schema_upgrade_is_idempotent_and_keeps_ledger(tmp_path):
    path = tmp_path / "db"
    db = sqlite3.connect(path)
    db.executescript(storage.SCHEMA)
    db.execute("INSERT INTO meta VALUES('paused','true')")
    db.commit()
    db.close()
    for _ in range(2):
        store = Store(path)
        try:
            assert store.meta("paused") is True
            assert store.db.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
            assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert store.db.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
            assert store.database_info["sqlite_version"] == sqlite3.sqlite_version
            assert store.database_info["user_version"] == storage.SCHEMA_VERSION
        finally:
            store.close()


def test_read_snapshot_cannot_recreate_a_missing_database(tmp_path):
    path = tmp_path / "db"
    store = Store(path)
    store.close()
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        with store.snapshot():
            pass
    assert not path.exists()


def test_wal_snapshot_stays_consistent_while_another_writer_commits(tmp_path):
    path = tmp_path / "db"
    store = Store(path)
    writer = Store(path)
    try:
        store.put_meta("version", 1)
        with store.snapshot() as db:
            assert db.execute("SELECT body FROM meta WHERE key='version'").fetchone()[0] == "1"
            writer.put_meta("version", 2)
            assert db.execute("SELECT body FROM meta WHERE key='version'").fetchone()[0] == "1"
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                db.execute("DELETE FROM meta")
        assert store.meta("version") == 2
    finally:
        writer.close()
        store.close()


def test_competing_connections_commit_without_lost_updates(tmp_path):
    path = tmp_path / "db"
    stores = [Store(path) for _ in range(4)]
    errors = []
    stores[0].put_meta("counter", 0)

    def write(store):
        try:
            for _ in range(30):
                with store.transaction() as db:
                    db.execute(
                        "UPDATE meta SET body=CAST(CAST(body AS INTEGER)+1 AS TEXT) WHERE key='counter'"
                    )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(s,)) for s in stores]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert not errors and not any(t.is_alive() for t in threads)
        assert stores[0].meta("counter") == 120
    finally:
        for t in threads:
            t.join(10)
        for s in stores:
            s.close()


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="POSIX crash recovery")
def test_process_death_preserves_commit_and_discards_uncommitted_writes(tmp_path):
    script = """
import os, signal, sys
from pathlib import Path
from capitalizator.fusion.store import Store
s=Store(Path(sys.argv[1]))
s.put_meta('committed', 1)
with s.transaction() as db:
    db.execute("INSERT INTO meta VALUES('uncommitted','2')")
    os.kill(os.getpid(), signal.SIGKILL)
"""
    path = tmp_path / "db"
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        env={**os.environ, "PYTHONPATH": str(Path(inspect.getfile(Store)).resolve().parents[2])},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr
    store = Store(path)
    try:
        assert store.meta("committed") == 1 and store.meta("uncommitted") is None
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        store.put_meta("after_restart", 3)
    finally:
        store.close()


def test_backup_closes_connections_and_restore_matches_checksums(tmp_path, monkeypatch):
    root, destination = tmp_path / "source", tmp_path / "backup"
    store = Store(root / "fusion.sqlite3")
    connections = track_connections(monkeypatch)
    try:
        for i in range(5):
            store.event(i, "BTCUSDT", "test", {"i": i})
        archive_events(store, root, 100, 3)
        checksums = backup(root, destination)
        for db in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                db.execute("SELECT 1")
        for name, digest in checksums.items():
            assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
        restored = Store(destination / "fusion.sqlite3")
        try:
            assert [json.loads(r["body"])["i"] for r in events(restored, destination)] == list(
                range(5)
            )
        finally:
            restored.close()
    finally:
        store.close()
        for db in connections:
            db.close()


def test_backup_rejects_valid_parquet_that_differs_from_ledger(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root, destination = tmp_path / "source", tmp_path / "backup"
    store = Store(root / "fusion.sqlite3")
    try:
        store.event(1, "BTCUSDT", "test", {"original": True})
        archive_events(store, root, 100, 1)
        path = next((root / "archive").glob("*.parquet"))
        rows = pq.read_table(path).to_pylist()
        rows[0]["body"] = '{"changed":true}'
        pq.write_table(pa.Table.from_pylist(rows), path)
        with pytest.raises(ValueError, match="archive checksum mismatch"):
            backup(root, destination)
        assert not (destination / "sha256.json").exists()
    finally:
        store.close()
