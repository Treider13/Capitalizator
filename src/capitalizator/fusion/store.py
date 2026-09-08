"""Durable events, contracts, models and exchange ledger with atomic risk reservations."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from capitalizator.fusion.concurrency import FairLock

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, received REAL NOT NULL, symbol TEXT NOT NULL,
 kind TEXT NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_clock ON events(received,id);
CREATE TABLE IF NOT EXISTS decisions(
 id INTEGER PRIMARY KEY, at REAL NOT NULL, symbol TEXT NOT NULL,
 kind TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS samples(
 id TEXT PRIMARY KEY, symbol TEXT NOT NULL, origin REAL NOT NULL,
 available REAL NOT NULL, x TEXT NOT NULL, y TEXT NOT NULL, context TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sample_clock ON samples(available);
CREATE INDEX IF NOT EXISTS sample_policy_clock
 ON samples(json_extract(context,'$.policy_version'),available,id);
CREATE TABLE IF NOT EXISTS models(
 version TEXT PRIMARY KEY, at REAL NOT NULL, body TEXT NOT NULL, report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contracts(
 id TEXT PRIMARY KEY, symbol TEXT NOT NULL, at REAL NOT NULL,
 state TEXT NOT NULL, definition TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY, mode TEXT NOT NULL, symbol TEXT NOT NULL,
 contract TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
 updated REAL NOT NULL, expires REAL NOT NULL, reserve REAL NOT NULL,
 body TEXT NOT NULL, venue_id TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS order_state ON orders(mode,state);
CREATE INDEX IF NOT EXISTS console_order_mode ON orders(mode);
CREATE TABLE IF NOT EXISTS executions(
 mode TEXT NOT NULL, id TEXT NOT NULL, order_id TEXT NOT NULL,
 symbol TEXT NOT NULL, at REAL NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(mode,id));
CREATE TABLE IF NOT EXISTS account(
 mode TEXT PRIMARY KEY, at REAL NOT NULL, equity REAL NOT NULL,
 day TEXT NOT NULL, day_start REAL NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS execution_symbol ON executions(mode,symbol,at);
CREATE INDEX IF NOT EXISTS console_execution_mode ON executions(mode);
CREATE INDEX IF NOT EXISTS contract_symbol ON contracts(symbol,at);
CREATE INDEX IF NOT EXISTS order_symbol ON orders(mode,symbol,created);
CREATE TABLE IF NOT EXISTS commands(
 id TEXT PRIMARY KEY, mode TEXT NOT NULL, symbol TEXT NOT NULL,
 kind TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS console_command_mode ON commands(mode);
CREATE TABLE IF NOT EXISTS dispatch(
 kind TEXT NOT NULL, id TEXT NOT NULL, attempted REAL NOT NULL, next_at REAL NOT NULL,
 error TEXT NOT NULL DEFAULT '', PRIMARY KEY(kind,id));
"""


def encode(body: Any) -> str:
    return json.dumps(body, sort_keys=True, allow_nan=False, separators=(",", ":"))


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = FairLock()
        self.analytics_lock = threading.Lock()
        self.db = sqlite3.connect(path, timeout=10, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self._check_schema_version()
            if self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError("SQLite WAL mode is required")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA busy_timeout=10000")
            self._initialize_schema()
            self.database_info = {
                "sqlite_version": sqlite3.sqlite_version,
                "sqlite_source_id": self.db.execute("SELECT sqlite_source_id()").fetchone()[0],
                **{
                    name: self.db.execute(f"PRAGMA {name}").fetchone()[0]
                    for name in ("user_version", "journal_mode", "synchronous", "busy_timeout")
                },
            }
        except BaseException as exc:
            try:
                self.db.close()
            except BaseException as close_error:
                exc.add_note(f"database close failed: {type(close_error).__name__}")
            raise

    def _check_schema_version(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(f"unsupported SQLite schema version: {version}")

    def _initialize_schema(self) -> None:
        with self.transaction() as db:
            # Recheck under the write lock in case another process upgraded it.
            self._check_schema_version()
            # executescript implicitly commits a pending transaction. Execute each
            # complete DDL statement instead, keeping schema and migration atomic.
            statement = ""
            for line in SCHEMA.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError("incomplete SQLite schema statement")
            if not db.execute("SELECT 1 FROM meta WHERE key='linear_ledger_v2'").fetchone():
                mixed_demo = db.execute(
                    "SELECT 1 FROM executions WHERE mode='demo' "
                    "AND json_extract(body,'$.category')<>'linear' LIMIT 1"
                ).fetchone()
                if mixed_demo:
                    # A previous qualification may contain invented cross-category
                    # episodes. Requalify once using the corrected calculation.
                    db.execute("DELETE FROM meta WHERE key='live_qualified_policy'")
                db.execute("INSERT INTO meta VALUES('linear_ledger_v2','true')")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Any:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException as exc:
                try:
                    # SQLITE_FULL and ON CONFLICT ROLLBACK may already end it.
                    if self.db.in_transaction:
                        self.db.execute("ROLLBACK")
                except BaseException as rollback_error:
                    exc.add_note(f"database rollback failed: {type(rollback_error).__name__}")
                    # A connection with an unresolved transaction must not be reused.
                    try:
                        self.db.close()
                    except BaseException as close_error:
                        exc.add_note(f"database close failed: {type(close_error).__name__}")
                raise

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    @contextmanager
    def snapshot(self) -> Any:
        """Independent WAL read transaction; archive rotation cannot change its view."""
        db = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10, isolation_level=None
        )
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            yield db
        finally:
            db.close()

    def meta(self, key: str, default: Any = None) -> Any:
        rows = self.rows("SELECT body FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["body"]) if rows else default

    def put_meta(self, key: str, value: Any) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, encode(value)))

    def event(self, at: float, symbol: str, kind: str, body: Any) -> int:
        with self.transaction() as db:
            return int(
                db.execute(
                    "INSERT INTO events(received,symbol,kind,body) VALUES(?,?,?,?)",
                    (at, symbol, kind, encode(body)),
                ).lastrowid
            )

    def decision(self, at: float, symbol: str, kind: str, body: Any) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO decisions(at,symbol,kind,body) VALUES(?,?,?,?)",
                (at, symbol, kind, encode(body)),
            )

    def sample(
        self,
        ident: str,
        symbol: str,
        origin: float,
        available: float,
        x: list[float],
        y: list[float],
        context: dict[str, Any],
    ) -> None:
        if available <= origin:
            raise ValueError("label must mature after its forecast")
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?,?,?)",
                (ident, symbol, origin, available, encode(x), encode(y), encode(context)),
            )

    def samples(self, at: float, limit: int, policy: str | None = None) -> list[dict[str, Any]]:
        rows = self.rows(
            "SELECT * FROM samples WHERE available<=? "
            + ("AND json_extract(context,'$.policy_version')=? " if policy else "")
            + "ORDER BY available DESC,id DESC LIMIT ?",
            (at, policy, limit) if policy else (at, limit),
        )
        for row in rows:
            for key in ("x", "y", "context"):
                row[key] = json.loads(row[key])
        return list(reversed(rows))

    def execution(self, mode: str, row: dict[str, Any]) -> bool:
        if row.get("category", "linear") != "linear":
            return False
        ident = str(row.get("execId") or "")
        if not ident:
            raise ValueError("execution missing execId")
        if mode not in {"demo", "live"}:
            raise ValueError("invalid execution mode")
        for key in ("execTime", "execQty", "execPrice", "execFee"):
            if not math.isfinite(float(row.get(key) or 0)):
                raise ValueError("nonfinite execution field: " + key)
        with self.transaction() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO executions VALUES(?,?,?,?,?,?)",
                (
                    mode,
                    ident,
                    str(row.get("orderLinkId") or ""),
                    str(row["symbol"]),
                    float(row["execTime"]) / 1000,
                    encode(row),
                ),
            )
            inserted = bool(cur.rowcount == 1)
            if inserted:
                key = "execution_revision:" + mode
                prior = db.execute("SELECT body FROM meta WHERE key=?", (key,)).fetchone()
                revision = int(prior["body"]) + 1 if prior else 1
                db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, str(revision)))
            return inserted

    def account(
        self,
        mode: str,
        at: float,
        equity: float,
        positions: list[Any],
        venue_orders: list[Any],
        day: str,
    ) -> None:
        if not math.isfinite(equity):
            raise ValueError("invalid equity")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM account WHERE mode=?", (mode,)).fetchone()
            start = old["day_start"] if old and old["day"] == day else equity
            db.execute(
                "INSERT OR REPLACE INTO account VALUES(?,?,?,?,?,?)",
                (
                    mode,
                    at,
                    equity,
                    day,
                    start,
                    encode({"positions": positions, "orders": venue_orders}),
                ),
            )

    def command(self, ident: str, mode: str, symbol: str, kind: str, at: float, body: Any) -> None:
        with self.transaction() as db:
            if kind == "flatten":
                # One unresolved close intent per account/symbol. Multiple triggers
                # must not create competing close IDs after an ambiguous send.
                existing = db.execute(
                    "SELECT id,body FROM commands WHERE mode=? AND symbol=? "
                    "AND kind='flatten' AND state IN ('pending','failed') LIMIT 1",
                    (mode, symbol),
                ).fetchone()
                if existing:
                    prior = json.loads(existing["body"])
                    if (
                        body.get("reason") == "operator"
                        and prior.get("close_rejected")
                        and not prior.get("close_attempted")
                    ):
                        # Explicit operator retry after a definitive rejection.
                        # Ambiguous sends never enter this branch.
                        prior.pop("close_rejected")
                        db.execute(
                            "UPDATE commands SET body=?,state='pending' WHERE id=?",
                            (encode(prior), existing["id"]),
                        )
                        db.execute(
                            "DELETE FROM dispatch WHERE kind='command' AND id=?", (existing["id"],)
                        )
                    return
            if kind == "stop":
                db.execute(
                    "UPDATE commands SET state='superseded' "
                    "WHERE mode=? AND symbol=? AND kind='stop' AND state='pending'",
                    (mode, symbol),
                )
            db.execute(
                "INSERT OR IGNORE INTO commands VALUES(?,?,?,?,?,?,?)",
                (ident, mode, symbol, kind, at, "pending", encode(body)),
            )

    def close(self) -> None:
        with self.lock:
            self.db.close()
