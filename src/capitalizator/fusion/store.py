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
CREATE TABLE IF NOT EXISTS executions(
 mode TEXT NOT NULL, id TEXT NOT NULL, order_id TEXT NOT NULL,
 symbol TEXT NOT NULL, at REAL NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(mode,id));
CREATE TABLE IF NOT EXISTS account(
 mode TEXT PRIMARY KEY, at REAL NOT NULL, equity REAL NOT NULL,
 day TEXT NOT NULL, day_start REAL NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS execution_symbol ON executions(mode,symbol,at);
CREATE INDEX IF NOT EXISTS contract_symbol ON contracts(symbol,at);
CREATE INDEX IF NOT EXISTS order_symbol ON orders(mode,symbol,created);
CREATE TABLE IF NOT EXISTS commands(
 id TEXT PRIMARY KEY, mode TEXT NOT NULL, symbol TEXT NOT NULL,
 kind TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL);
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
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Any:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

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
                    "SELECT id FROM commands WHERE mode=? AND symbol=? "
                    "AND kind='flatten' AND state='pending' LIMIT 1",
                    (mode, symbol),
                ).fetchone()
                if existing:
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
