"""SQLite knowledge base. Same idea as Freqtrade tradesv3.sqlite — portable file.

Empty tables are honest. Does not read keys. Does not open size.
Open with create=False never writes: missing file stays missing; a 0-byte
desk.sqlite is not a db (SQLite would init it). Readonly bind via mode=ro.
Writes take BEGIN IMMEDIATE. Snapshot uses sqlite3 backup API, not a raw file copy.
Episode and report rows are bound into the hash chain in the same transaction.
verify_tables() replays those links; a silent UPDATE of episodes fails pack.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from capitalizator.memory.hashlog import GENESIS, HashChain, HashLink
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.vault import (
    Vault,
    VaultError,
    open_real_dir_fd,
    same_inode,
    write_regular_bytes,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hash_links (
  id INTEGER PRIMARY KEY,
  prev_hash TEXT NOT NULL,
  payload TEXT NOT NULL,
  digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
  trade_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  gesture TEXT NOT NULL,
  fill TEXT NOT NULL,
  slip TEXT NOT NULL,
  fees TEXT NOT NULL,
  r TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  day TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  PRIMARY KEY (day, kind)
);
CREATE TABLE IF NOT EXISTS journal_touches (
  touch_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intent_queue (
  id INTEGER PRIMARY KEY,
  created_ts TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_queue (
  id INTEGER PRIMARY KEY,
  intent_id INTEGER,
  created_ts TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS overlay (
  setup_id TEXT PRIMARY KEY,
  r_shadow TEXT,
  r_demo TEXT,
  r_live TEXT
);
CREATE TABLE IF NOT EXISTS market_event (
  id INTEGER PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS zone (
  zone_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS author_call (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news (
  event_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_r (
  setup_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
"""

EPISODE_MODES = frozenset({"shadow", "demo", "micro", "live"})
EPISODE_KEYS = ("trade_id", "mode", "zone_id", "gesture", "fill", "slip", "fees", "r")
EMPTY_COUNTS = {"hash_links": 0, "episodes": 0, "reports": 0}


def episode_payload(row: Mapping[str, str]) -> str:
    body = {"k": "episode", **{key: str(row[key]) for key in EPISODE_KEYS}}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def report_payload(*, day: str, kind: str, body: str) -> str:
    return json.dumps(
        {"k": "report", "day": day, "kind": kind, "body": body},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def connect_held_inode(fd: int, *, readonly: bool = False) -> sqlite3.Connection:
    """Bind SQLite to the inode we already opened with O_NOFOLLOW.

    sqlite3.connect(path) follows a symlink planted after the probe fd is closed.
    /proc/self/fd/N opens that inode (Linux). Journal stays next to the real file;
    a later connect(path) sees the same bytes. stdlib has no SQLITE_OPEN_NOFOLLOW.
    create=False uses file:?mode=ro so SCHEMA / INSERT cannot dirty the source.
    """
    proc = f"/proc/self/fd/{int(fd)}"
    if not os.path.exists(proc):
        raise ValueError("sqlite open requires /proc/self/fd")
    if readonly:
        return sqlite3.connect(f"file:{proc}?mode=ro", uri=True, timeout=5.0)
    return sqlite3.connect(proc, timeout=5.0)


class Knowledge:
    def __init__(self, path: Path, *, create: bool = True) -> None:
        self.path = path
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ValueError("O_NOFOLLOW required")
        if path.is_symlink():
            raise ValueError(f"symlink: {path}")
        # os.open(path, O_NOFOLLOW) follows a parent dir symlink (last component only).
        dir_fd = -1
        fd = -1
        try:
            try:
                dir_fd = open_real_dir_fd(path.parent, create=create)
            except VaultError as exc:
                if create or "symlink" in str(exc):
                    raise ValueError(str(exc)) from exc
                self._cx: sqlite3.Connection | None = None
                return
            flags = (os.O_RDWR if create else os.O_RDONLY) | nofollow
            if create:
                try:
                    fd = os.open(
                        path.name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dir_fd
                    )
                except FileExistsError:
                    fd = os.open(path.name, flags, dir_fd=dir_fd)
            else:
                try:
                    fd = os.open(path.name, flags, dir_fd=dir_fd)
                except FileNotFoundError:
                    self._cx = None
                    return
            created = os.fstat(fd)
            if not stat.S_ISREG(created.st_mode):
                raise ValueError(f"not a regular file: {path}")
            if created.st_nlink > 1:
                raise ValueError(f"hardlink: {path}")
            # Fact: SQLite treats a 0-byte file as a new db and writes a header
            # even when the URI is mode=ro (select 1 succeeds; pack then snapshots).
            if not create and created.st_size == 0:
                raise ValueError(f"empty knowledge db: {path}")
            if create:
                os.fchmod(fd, 0o600)
            self._cx = connect_held_inode(fd, readonly=not create)
        finally:
            if fd >= 0:
                os.close(fd)
            if dir_fd >= 0:
                os.close(dir_fd)
        if path.is_symlink() or not same_inode(path, created):
            self._cx.close()
            self._cx = None
            raise ValueError(f"symlink: {path}")
        self._cx.isolation_level = None
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        if create:
            self._cx.executescript(SCHEMA)
            self._cx.execute("INSERT OR IGNORE INTO meta(k, v) VALUES ('schema', '1')")
            self._cx.execute("PRAGMA secure_delete = ON")
        else:
            try:
                self._cx.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            except sqlite3.DatabaseError as exc:
                raise ValueError(f"not a sqlite database: {path}") from exc

    def close(self) -> None:
        if self._cx is not None:
            self._cx.close()
            self._cx = None

    def available(self) -> bool:
        return self._cx is not None

    def table_names(self) -> set[str]:
        if self._cx is None:
            return set()
        rows = self._cx.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {str(row["name"]) for row in rows}

    def meta(self, key: str) -> str | None:
        if self._cx is None:
            return None
        if not key or contains_advice(key):
            raise ValueError("meta key refused")
        row = self._cx.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        if row is None:
            return None
        return str(row["v"])

    def set_meta(self, key: str, value: str) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if not key or contains_advice(key) or contains_advice(value):
            raise ValueError("meta must not advise")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)",
                (key, value),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def counts(self) -> dict[str, int]:
        if self._cx is None:
            return dict(EMPTY_COUNTS)
        out: dict[str, int] = {}
        for table in ("hash_links", "episodes", "reports"):
            row = self._cx.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"])
        return out

    def integrity_ok(self) -> bool:
        if self._cx is None:
            return True
        row = self._cx.execute("PRAGMA integrity_check").fetchone()
        return row is not None and str(row[0]) == "ok"

    def snapshot_to(self, dest: Path) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db to snapshot")
        mem = sqlite3.connect(":memory:")
        try:
            self._cx.backup(mem)
            # sqlite/sqlite ext/misc/scrub.c: DELETE leaves reusable pages; VACUUM
            # rebuilds the copy. backup+serialize without it can ship deleted cells.
            mem.execute("VACUUM")
            row = mem.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]) != "ok":
                raise ValueError("integrity_check failed after snapshot")
            blob = mem.serialize()
        finally:
            mem.close()
        try:
            write_regular_bytes(dest, blob)
        except VaultError as exc:
            raise ValueError(str(exc)) from exc

    def _insert_link(self, payload: str) -> HashLink:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        prev = GENESIS
        last = self._cx.execute(
            "SELECT digest FROM hash_links ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last is not None:
            prev = str(last["digest"])
        chain = HashChain()
        chain.links = self.links()
        link = chain.append(payload)
        if link.prev_hash != prev:
            raise ValueError("hash prev mismatch")
        self._cx.execute(
            "INSERT INTO hash_links(prev_hash, payload, digest) VALUES (?, ?, ?)",
            (link.prev_hash, link.payload, link.digest),
        )
        return link

    def append_link(self, payload: str) -> HashLink:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            link = self._insert_link(payload)
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        return link

    def links(self) -> list[HashLink]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT prev_hash, payload, digest FROM hash_links ORDER BY id"
        ).fetchall()
        return [
            HashLink(
                prev_hash=str(row["prev_hash"]),
                payload=str(row["payload"]),
                digest=str(row["digest"]),
            )
            for row in rows
        ]

    def verify_chain(self) -> bool:
        chain = HashChain()
        chain.links = self.links()
        return chain.verify()

    def verify_tables(self) -> bool:
        """Replay episode/report links. A silent table UPDATE must not pass."""
        if self._cx is None:
            return True
        expected_ep: dict[str, dict[str, str]] = {}
        expected_rep: dict[tuple[str, str], str] = {}
        for link in self.links():
            try:
                obj = json.loads(link.payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            kind = obj.get("k")
            if kind == "episode":
                row = {key: str(obj.get(key, "")) for key in EPISODE_KEYS}
                expected_ep[row["trade_id"]] = row
            elif kind == "report":
                day = str(obj.get("day", ""))
                report_kind = str(obj.get("kind", ""))
                expected_rep[(day, report_kind)] = str(obj.get("body", ""))
        got_ep = {
            row["trade_id"]: {key: row[key] for key in EPISODE_KEYS} for row in self.episodes()
        }
        if got_ep != expected_ep:
            return False
        got_rep: dict[tuple[str, str], str] = {}
        for row in self._cx.execute("SELECT day, kind, body FROM reports"):
            got_rep[(str(row["day"]), str(row["kind"]))] = str(row["body"])
        return got_rep == expected_rep

    def verify_ok(self) -> bool:
        return self.verify_chain() and self.verify_tables() and self.integrity_ok()

    def append_episode(self, row: Mapping[str, Any]) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        required = ("trade_id", "mode", "zone_id", "gesture", "fill", "slip", "fees", "r")
        missing = [k for k in required if k not in row]
        if missing:
            raise ValueError(f"episode missing: {missing}")
        if row["mode"] not in EPISODE_MODES:
            raise ValueError(
                f"episode.mode must be shadow|demo|micro|live, got {row['mode']!r}"
            )
        fill = row["fill"]
        fill_text = fill.isoformat() if isinstance(fill, datetime) else str(fill)
        stored = {
            "trade_id": str(row["trade_id"]),
            "mode": str(row["mode"]),
            "zone_id": str(row["zone_id"]),
            "gesture": str(row["gesture"]),
            "fill": fill_text,
            "slip": str(row["slip"]),
            "fees": str(row["fees"]),
            "r": str(row["r"]),
        }
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                """
                INSERT INTO episodes(trade_id, mode, zone_id, gesture, fill, slip, fees, r)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(stored[key] for key in EPISODE_KEYS),
            )
            self._insert_link(episode_payload(stored))
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def episodes(self) -> list[dict[str, str]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT trade_id, mode, zone_id, gesture, fill, slip, fees, r "
            "FROM episodes ORDER BY fill"
        ).fetchall()
        return [{k: str(row[k]) for k in row.keys()} for row in rows]

    def save_report(self, *, day: str, kind: str, body: str) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if contains_advice(body) or contains_advice(day) or contains_advice(kind):
            raise ValueError("report must not advise")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO reports(day, kind, body) VALUES (?, ?, ?)",
                (day, kind, body),
            )
            self._insert_link(report_payload(day=day, kind=kind, body=body))
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def report(self, *, day: str, kind: str = "map") -> str | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT body FROM reports WHERE day = ? AND kind = ?",
            (day, kind),
        ).fetchone()
        if row is None:
            return None
        return str(row["body"])

    def all_text(self) -> str:
        parts: list[str] = []
        for row in self.episodes():
            parts.extend(row.values())
        if self._cx is not None:
            for row in self._cx.execute("SELECT day, kind, body FROM reports"):
                parts.extend(str(row[k]) for k in row.keys())
            for row in self._cx.execute("SELECT k, v FROM meta"):
                parts.extend((str(row["k"]), str(row["v"])))
        for link in self.links():
            parts.append(link.payload)
        return "\n".join(parts)

    def latest_report(self) -> dict[str, str] | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT day, kind, body FROM reports ORDER BY day DESC, kind LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {"day": str(row["day"]), "kind": str(row["kind"]), "body": str(row["body"])}


    def put_journal_touch(self, touch_id: str, payload: Mapping[str, Any]) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO journal_touches(touch_id, payload) VALUES (?, ?)",
                (str(touch_id), body),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def journal_rows(self) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute("SELECT payload FROM journal_touches").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            raw = json.loads(str(row["payload"]))
            if isinstance(raw, dict):
                out.append(raw)
        return out

    def overlay_rows(self) -> list[dict[str, str | None]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT setup_id, r_shadow, r_demo, r_live FROM overlay"
        ).fetchall()
        return [
            {
                "setup_id": str(row["setup_id"]),
                "r_shadow": None if row["r_shadow"] is None else str(row["r_shadow"]),
                "r_demo": None if row["r_demo"] is None else str(row["r_demo"]),
                "r_live": None if row["r_live"] is None else str(row["r_live"]),
            }
            for row in rows
        ]

    def get_journal_touch(self, touch_id: str) -> dict[str, Any] | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT payload FROM journal_touches WHERE touch_id = ?",
            (touch_id,),
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(str(row["payload"]))
        return raw if isinstance(raw, dict) else None

    def enqueue_intent(self, payload: Mapping[str, Any], *, created_ts: str) -> int:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            cur = self._cx.execute(
                "INSERT INTO intent_queue(created_ts, status, payload) VALUES (?, ?, ?)",
                (created_ts, "pending", body),
            )
            row_id = int(cur.lastrowid or 0)
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        return row_id

    def pending_intents(self) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT id, created_ts, status, payload FROM intent_queue "
            "WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            out.append(
                {
                    "id": int(row["id"]),
                    "created_ts": str(row["created_ts"]),
                    "status": str(row["status"]),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        return out

    def mark_intent(self, intent_id: int, status: str) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if status not in {"pending", "sent", "skipped", "failed"}:
            raise ValueError(f"bad intent status: {status!r}")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "UPDATE intent_queue SET status = ? WHERE id = ?",
                (status, int(intent_id)),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def enqueue_order(
        self,
        payload: Mapping[str, Any],
        *,
        created_ts: str,
        intent_id: int | None = None,
        status: str = "accepted",
    ) -> int:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            cur = self._cx.execute(
                "INSERT INTO order_queue(intent_id, created_ts, status, payload) "
                "VALUES (?, ?, ?, ?)",
                (intent_id, created_ts, status, body),
            )
            row_id = int(cur.lastrowid or 0)
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        return row_id

    def put_overlay(
        self,
        setup_id: str,
        *,
        r_shadow: str | None = None,
        r_demo: str | None = None,
        r_live: str | None = None,
    ) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO overlay(setup_id, r_shadow, r_demo, r_live) "
                "VALUES (?, ?, ?, ?)",
                (setup_id, r_shadow, r_demo, r_live),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def get_overlay(self, setup_id: str) -> dict[str, str | None] | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT setup_id, r_shadow, r_demo, r_live FROM overlay WHERE setup_id = ?",
            (setup_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "setup_id": str(row["setup_id"]),
            "r_shadow": None if row["r_shadow"] is None else str(row["r_shadow"]),
            "r_demo": None if row["r_demo"] is None else str(row["r_demo"]),
            "r_live": None if row["r_live"] is None else str(row["r_live"]),
        }


def open_knowledge(vault: Vault, *, create: bool = True) -> Knowledge:
    return Knowledge(vault.db_path, create=create)
