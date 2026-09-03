"""SQLite knowledge base. Same idea as Freqtrade tradesv3.sqlite — portable file.

Empty tables are honest. Does not read keys. Does not open size.
Open with create=False never writes: missing file stays missing; a 0-byte
desk.sqlite is not a db (SQLite would init it). Readonly bind via mode=ro.
Writes take BEGIN IMMEDIATE. Writable opens set PRAGMA journal_mode=WAL.
Snapshot uses sqlite3 backup API, not a raw file copy.
Episode and report rows are bound into the hash chain in the same transaction.
verify_tables() replays those links; a silent UPDATE of episodes fails pack.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
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
  r_live TEXT,
  r_challenger TEXT
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
CREATE TABLE IF NOT EXISTS paper_trades (
  paper_id TEXT PRIMARY KEY,
  touch_id TEXT NOT NULL,
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  closed_at TEXT,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_trades_touch ON paper_trades(touch_id);
CREATE INDEX IF NOT EXISTS paper_trades_closed ON paper_trades(closed_at);
CREATE TABLE IF NOT EXISTS oms_commands (
  id INTEGER PRIMARY KEY,
  created_ts TEXT NOT NULL,
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  symbol TEXT NOT NULL,
  payload TEXT NOT NULL,
  result TEXT
);
CREATE TABLE IF NOT EXISTS intent_result (
  intent_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intel_item (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  source_id TEXT NOT NULL,
  known_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS intel_item_known ON intel_item(known_at);
CREATE TABLE IF NOT EXISTS desk_commands (
  id INTEGER PRIMARY KEY,
  created_ts TEXT NOT NULL,
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  result TEXT
);
CREATE INDEX IF NOT EXISTS desk_commands_status ON desk_commands(status);
CREATE INDEX IF NOT EXISTS intent_queue_status ON intent_queue(status);
CREATE INDEX IF NOT EXISTS oms_commands_status ON oms_commands(status);
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
        self._on_work: Callable[[], None] | None = None
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
            self._cx.execute("PRAGMA journal_mode = WAL")
            self._cx.executescript(SCHEMA)
            self._cx.execute("INSERT OR IGNORE INTO meta(k, v) VALUES ('schema', '1')")
            self._cx.execute("PRAGMA secure_delete = ON")
            self._ensure_overlay_r_challenger()
        else:
            try:
                self._cx.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            except sqlite3.DatabaseError as exc:
                raise ValueError(f"not a sqlite database: {path}") from exc

    def set_on_work(self, fn: Callable[[], None] | None) -> None:
        self._on_work = fn

    def _notify_work(self) -> None:
        if self._on_work is not None:
            self._on_work()

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

    def set_meta_many(self, rows: Mapping[str, str]) -> None:
        """One BEGIN IMMEDIATE for a batch of meta keys (UI snapshots, counters)."""
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if not rows:
            return
        for key, value in rows.items():
            if not key or contains_advice(key) or contains_advice(value):
                raise ValueError("meta must not advise")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.executemany(
                "INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)",
                list(rows.items()),
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

    def claim_count(self, prefix: str) -> int:
        """How many claim rows share this id prefix. Does not invent cards."""
        if self._cx is None:
            return 0
        if not prefix or contains_advice(prefix):
            raise ValueError("claim prefix refused")
        row = self._cx.execute(
            "SELECT COUNT(*) AS n FROM claim WHERE id LIKE ?",
            (f"{prefix}%",),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

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


    def put_card_live(self, symbol: str, payload: Mapping[str, Any]) -> None:
        """Contour B bus. claim id b_card:SYMBOL. Does not enqueue an intent."""
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if not symbol or contains_advice(symbol):
            raise ValueError("card symbol refused")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        if contains_advice(body):
            raise ValueError("card payload must not advise")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO claim(id, payload) VALUES (?, ?)",
                (f"b_card:{symbol}", body),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def get_card_live(self, symbol: str) -> dict[str, Any] | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT payload FROM claim WHERE id = ?",
            (f"b_card:{symbol}",),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            return None
        return raw if isinstance(raw, dict) else None

    def put_spot_ack(self, symbol: str, payload: Mapping[str, Any]) -> None:
        """Variant-2 rail. claim id spot_ack:SYMBOL. Does not enqueue an intent."""
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if not symbol or contains_advice(symbol):
            raise ValueError("spot symbol refused")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        if contains_advice(body):
            raise ValueError("spot ack must not advise")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO claim(id, payload) VALUES (?, ?)",
                (f"spot_ack:{symbol}", body),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def get_spot_ack(self, symbol: str) -> dict[str, Any] | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT payload FROM claim WHERE id = ?",
            (f"spot_ack:{symbol}",),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            return None
        return raw if isinstance(raw, dict) else None

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
        rows = self._cx.execute("SELECT touch_id, payload FROM journal_touches").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            raw = json.loads(str(row["payload"]))
            if isinstance(raw, dict):
                # The row key is a fact of the row: readers (night map, revive, UI) must
                # not depend on the writer having copied it into the payload.
                raw.setdefault("touch_id", str(row["touch_id"]))
                out.append(raw)
        return out

    def _overlay_cols(self) -> set[str]:
        if self._cx is None:
            return set()
        rows = self._cx.execute("PRAGMA table_info(overlay)").fetchall()
        return {str(row[1]) for row in rows}

    def _ensure_overlay_r_challenger(self) -> None:
        """Additive. Old desk.sqlite has overlay without r_challenger."""
        if self._cx is None or "r_challenger" in self._overlay_cols():
            return
        try:
            self._cx.execute("ALTER TABLE overlay ADD COLUMN r_challenger TEXT")
        except sqlite3.OperationalError:
            return

    def _overlay_dict(self, row: sqlite3.Row) -> dict[str, str | None]:
        keys = ("r_shadow", "r_demo", "r_live", "r_challenger")
        out: dict[str, str | None] = {"setup_id": str(row["setup_id"])}
        for key in keys:
            try:
                raw = row[key]
            except (KeyError, IndexError):
                raw = None
            out[key] = None if raw is None else str(raw)
        return out

    def overlay_rows(self) -> list[dict[str, str | None]]:
        if self._cx is None:
            return []
        cols = "setup_id, r_shadow, r_demo, r_live"
        if "r_challenger" in self._overlay_cols():
            cols += ", r_challenger"
        rows = self._cx.execute(f"SELECT {cols} FROM overlay").fetchall()
        return [self._overlay_dict(row) for row in rows]

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
        self._notify_work()
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

    # `unknown`: transport failed after the order left — the venue may hold it; the
    # signer resolves it by orderLinkId. `no_gateway`: no key/process to send with;
    # the desk keeps the idea and the row is re-sent when a gateway appears.
    INTENT_STATUSES = frozenset(
        {"pending", "sent", "skipped", "failed", "rejected", "unknown", "no_gateway"}
    )

    def mark_intent(
        self, intent_id: int, status: str, result: Mapping[str, Any] | None = None
    ) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if status not in self.INTENT_STATUSES:
            raise ValueError(f"bad intent status: {status!r}")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "UPDATE intent_queue SET status = ? WHERE id = ?",
                (status, int(intent_id)),
            )
            if result is not None:
                self._cx.execute(
                    "INSERT OR REPLACE INTO intent_result(intent_id, status, body) "
                    "VALUES (?, ?, ?)",
                    (
                        int(intent_id),
                        status,
                        json.dumps(dict(result), sort_keys=True, default=str),
                    ),
                )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def intents_with_status(self, status: str) -> list[dict[str, Any]]:
        """Rows in one state, with the last recorded result (if any)."""
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT q.id, q.created_ts, q.status, q.payload, r.body AS result "
            "FROM intent_queue q LEFT JOIN intent_result r ON r.intent_id = q.id "
            "WHERE q.status = ? ORDER BY q.id",
            (status,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            result = json.loads(str(row["result"])) if row["result"] else None
            out.append(
                {
                    "id": int(row["id"]),
                    "created_ts": str(row["created_ts"]),
                    "status": str(row["status"]),
                    "payload": payload if isinstance(payload, dict) else {},
                    "result": result if isinstance(result, dict) else None,
                }
            )
        return out

    # --- operator → desk / signer commands (transactional, no read-modify-write) --------
    COMMAND_KINDS = frozenset(
        {
            "flatten",
            "release_halts",
            "pause_entries",
            "resume_entries",
            "release_signer",  # clear the sticky entry block after a reconcile mismatch
            "ack_position",  # operator claims an unknown venue position
            "promote",  # champion ← challenger, with the exam report attached
            "drift_release",  # clear a window's Page-Hinkley size cut
        }
    )

    def enqueue_command(
        self, kind: str, payload: Mapping[str, Any], *, created_ts: str
    ) -> int:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if kind not in self.COMMAND_KINDS:
            raise ValueError(f"unknown command kind: {kind!r}")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            cur = self._cx.execute(
                "INSERT INTO desk_commands(created_ts, status, kind, payload) VALUES (?, ?, ?, ?)",
                (created_ts, "pending", kind, body),
            )
            row_id = int(cur.lastrowid or 0)
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        self._notify_work()
        return row_id

    def claim_commands(self, kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Atomically move pending commands to `claimed` and return them. Two consumers
        (desk, signer) never see the same row; a crash between claim and done leaves
        the row `claimed` for the operator to see, never silently dropped."""
        if self._cx is None:
            return []
        wanted = None if kinds is None else sorted(set(kinds))
        # cheap read first: no writer lock when the queue is empty (it is, 99.9% of ticks)
        probe = (
            "SELECT 1 FROM desk_commands WHERE status = 'pending'"
            + (" AND kind IN (" + ",".join("?" for _ in wanted) + ")" if wanted else "")
            + " LIMIT 1"
        )
        if self._cx.execute(probe, tuple(wanted or ())).fetchone() is None:
            return []
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            if wanted:
                marks = ",".join("?" for _ in wanted)
                rows = self._cx.execute(
                    "SELECT id, created_ts, kind, payload FROM desk_commands "
                    f"WHERE status = 'pending' AND kind IN ({marks}) ORDER BY id",
                    tuple(wanted),
                ).fetchall()
            else:
                rows = self._cx.execute(
                    "SELECT id, created_ts, kind, payload FROM desk_commands "
                    "WHERE status = 'pending' ORDER BY id"
                ).fetchall()
            ids = [int(r["id"]) for r in rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                self._cx.execute(
                    f"UPDATE desk_commands SET status = 'claimed' WHERE id IN ({marks})",
                    tuple(ids),
                )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            out.append(
                {
                    "id": int(row["id"]),
                    "created_ts": str(row["created_ts"]),
                    "kind": str(row["kind"]),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        return out

    def mark_command(
        self, cmd_id: int, status: str, result: Mapping[str, Any] | None = None
    ) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if status not in {"pending", "claimed", "done", "failed"}:
            raise ValueError(f"bad command status: {status!r}")
        body = None if result is None else json.dumps(dict(result), sort_keys=True, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "UPDATE desk_commands SET status = ?, result = ? WHERE id = ?",
                (status, body, int(cmd_id)),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def commands(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT id, created_ts, status, kind, payload, result FROM desk_commands "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            result = json.loads(str(row["result"])) if row["result"] else None
            out.append(
                {
                    "id": int(row["id"]),
                    "created_ts": str(row["created_ts"]),
                    "status": str(row["status"]),
                    "kind": str(row["kind"]),
                    "payload": payload if isinstance(payload, dict) else {},
                    "result": result,
                }
            )
        return out

    def intent_result(self, intent_id: int) -> dict[str, Any] | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT body FROM intent_result WHERE intent_id = ?", (int(intent_id),)
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(str(row["body"]))
        return raw if isinstance(raw, dict) else None

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
        r_challenger: str | None = None,
    ) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        self._ensure_overlay_r_challenger()
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            if "r_challenger" in self._overlay_cols():
                self._cx.execute(
                    "INSERT OR REPLACE INTO overlay"
                    "(setup_id, r_shadow, r_demo, r_live, r_challenger) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (setup_id, r_shadow, r_demo, r_live, r_challenger),
                )
            else:
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
        cols = "setup_id, r_shadow, r_demo, r_live"
        if "r_challenger" in self._overlay_cols():
            cols += ", r_challenger"
        row = self._cx.execute(
            f"SELECT {cols} FROM overlay WHERE setup_id = ?",
            (setup_id,),
        ).fetchone()
        if row is None:
            return None
        return self._overlay_dict(row)

    def _put_keyed_payload(
        self, table: str, key_col: str, key: str, payload: Mapping[str, Any]
    ) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                f"INSERT OR REPLACE INTO {table}({key_col}, payload) VALUES (?, ?)",
                (str(key), body),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def _list_payloads(self, table: str) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(f"SELECT payload FROM {table}").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            raw = json.loads(str(row["payload"]))
            if isinstance(raw, dict):
                out.append(raw)
        return out

    # --- intel items (contour B raw material, point-in-time) --------------------------
    def put_intel_item(
        self, item_id: str, *, kind: str, source_id: str, known_at: str, payload: Mapping[str, Any]
    ) -> bool:
        """Insert once; returns False when the id was already stored (dedup by id)."""
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            cur = self._cx.execute(
                "INSERT OR IGNORE INTO intel_item(id, kind, source_id, known_at, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (item_id, kind, source_id, known_at, body),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        return bool(cur.rowcount)

    def intel_items(
        self, *, kind: str | None = None, since: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        sql = "SELECT id, kind, source_id, known_at, payload FROM intel_item"
        where: list[str] = []
        args: list[Any] = []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if since:
            where.append("known_at >= ?")
            args.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY known_at DESC LIMIT ?"
        args.append(int(limit))
        out: list[dict[str, Any]] = []
        for row in self._cx.execute(sql, tuple(args)).fetchall():
            payload = json.loads(str(row["payload"]))
            out.append(
                {
                    "id": str(row["id"]),
                    "kind": str(row["kind"]),
                    "source_id": str(row["source_id"]),
                    "known_at": str(row["known_at"]),
                    **(payload if isinstance(payload, dict) else {}),
                }
            )
        return out

    def put_author_call(self, call_id: str, payload: Mapping[str, Any]) -> None:
        self._put_keyed_payload("author_call", "id", call_id, payload)

    def author_calls(self) -> list[dict[str, Any]]:
        return self._list_payloads("author_call")

    # --- OMS commands: desk decides, gateway executes (amend_stop / trailing / half_tp / flatten)
    def enqueue_oms(
        self, *, kind: str, symbol: str, payload: Mapping[str, Any], created_ts: str
    ) -> int:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if kind not in {"amend_stop", "set_trailing", "half_tp", "flatten", "cancel_entries"}:
            raise ValueError(f"unknown oms kind: {kind!r}")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            cur = self._cx.execute(
                "INSERT INTO oms_commands(created_ts, status, kind, symbol, payload) "
                "VALUES (?, 'pending', ?, ?, ?)",
                (created_ts, kind, symbol, body),
            )
            row_id = int(cur.lastrowid or 0)
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        self._notify_work()
        return row_id

    def pending_oms(self) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT id, created_ts, kind, symbol, payload FROM oms_commands "
            "WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            out.append(
                {
                    "id": int(row["id"]),
                    "created_ts": str(row["created_ts"]),
                    "kind": str(row["kind"]),
                    "symbol": str(row["symbol"]),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        return out

    def mark_oms(self, cmd_id: int, status: str, result: Mapping[str, Any] | None = None) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if status not in {"pending", "done", "failed", "skipped"}:
            raise ValueError(f"bad oms status: {status!r}")
        body = None if result is None else json.dumps(dict(result), sort_keys=True, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "UPDATE oms_commands SET status = ?, result = ? WHERE id = ?",
                (status, body, int(cmd_id)),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def oms_rows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT id, created_ts, status, kind, symbol, payload, result FROM oms_commands "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "created_ts": str(r["created_ts"]),
                "status": str(r["status"]),
                "kind": str(r["kind"]),
                "symbol": str(r["symbol"]),
                "payload": json.loads(str(r["payload"])),
                "result": None if r["result"] is None else json.loads(str(r["result"])),
            }
            for r in rows
        ]

    def intent_status(self, intent_id: int) -> str | None:
        if self._cx is None:
            return None
        row = self._cx.execute(
            "SELECT status FROM intent_queue WHERE id = ?", (int(intent_id),)
        ).fetchone()
        return None if row is None else str(row["status"])

    def intent_rows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Every intent with its status — the UI must show failed/rejected, not hide them."""
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT id, created_ts, status, payload FROM intent_queue ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "created_ts": str(r["created_ts"]),
                "status": str(r["status"]),
                "payload": json.loads(str(r["payload"])),
            }
            for r in rows
        ]

    def order_rows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        rows = self._cx.execute(
            "SELECT id, intent_id, created_ts, status, payload FROM order_queue "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "intent_id": r["intent_id"],
                "created_ts": str(r["created_ts"]),
                "status": str(r["status"]),
                "payload": json.loads(str(r["payload"])),
            }
            for r in rows
        ]

    def put_paper_trade(self, payload: Mapping[str, Any]) -> None:
        """Closed paper position (exec/paper.py). Keyed by paper_id; indexed by touch."""
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                "INSERT OR REPLACE INTO paper_trades"
                "(paper_id, touch_id, source, symbol, closed_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(payload["paper_id"]),
                    str(payload.get("touch_id") or ""),
                    str(payload.get("source") or ""),
                    str(payload.get("symbol") or ""),
                    None if payload.get("closed_at") is None else str(payload["closed_at"]),
                    body,
                ),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def paper_trades(
        self,
        *,
        source: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self._cx is None:
            return []
        sql = "SELECT payload FROM paper_trades"
        where: list[str] = []
        args: list[Any] = []
        if source is not None:
            where.append("source = ?")
            args.append(source)
        if since is not None:
            where.append("closed_at >= ?")
            args.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY closed_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        out: list[dict[str, Any]] = []
        for row in self._cx.execute(sql, args).fetchall():
            raw = json.loads(str(row["payload"]))
            if isinstance(raw, dict):
                out.append(raw)
        return out

    def put_zone(self, zone_id: str, payload: Mapping[str, Any]) -> None:
        self._put_keyed_payload("zone", "zone_id", zone_id, payload)

    def drop_zone(self, zone_id: str) -> None:
        """Remove one zone row. PK is zone_id; a tf change is a new row, not REPLACE."""
        self.apply_zone_writes(drop_ids=(zone_id,))

    def apply_zone_writes(
        self,
        *,
        drop_ids: Sequence[str] = (),
        puts: Sequence[tuple[str, Mapping[str, Any]]] = (),
    ) -> None:
        """One BEGIN IMMEDIATE for drop+put. Same rule as episode+hash in this file.

        Console and desk open separate connections to one sqlite file. Split
        drop-then-put commits left a reader with neither the old 1d nor the new 15m.
        """
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        if not drop_ids and not puts:
            return
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            for zid in drop_ids:
                self._cx.execute("DELETE FROM zone WHERE zone_id = ?", (str(zid),))
            for zid, payload in puts:
                body = json.dumps(
                    dict(payload), sort_keys=True, ensure_ascii=False, default=str
                )
                self._cx.execute(
                    "INSERT OR REPLACE INTO zone(zone_id, payload) VALUES (?, ?)",
                    (str(zid), body),
                )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise

    def list_zones(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        rows = self._list_payloads("zone")
        if symbol is None:
            return rows
        return [row for row in rows if str(row.get("symbol") or "") == symbol]

    def put_claim(self, claim_id: str, payload: Mapping[str, Any]) -> None:
        self._put_keyed_payload("claim", "id", claim_id, payload)

    def list_claims(self, *, card_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._list_payloads("claim")
        if card_id is None:
            return rows
        return [row for row in rows if str(row.get("card_id") or "") == card_id]

    def meta_prefix(self, prefix: str) -> dict[str, str]:
        if self._cx is None or not prefix:
            return {}
        rows = self._cx.execute(
            "SELECT k, v FROM meta WHERE k LIKE ?",
            (f"{prefix}%",),
        ).fetchall()
        return {str(row["k"]): str(row["v"]) for row in rows}

    def last_prices(self) -> dict[str, str]:
        raw = self.meta_prefix("last_price:")
        return {key.split(":", 1)[1]: value for key, value in raw.items() if ":" in key}

    def put_last_price(self, symbol: str, price: str) -> None:
        self.set_meta(f"last_price:{symbol}", str(price))

    def put_book_levels(self, symbol: str, payload: Mapping[str, Any]) -> None:
        body = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        self.set_meta(f"book:{symbol}", body)

    def book_levels(self, symbol: str) -> dict[str, Any] | None:
        raw = self.meta(f"book:{symbol}")
        if raw is None:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None


def open_knowledge(vault: Vault, *, create: bool = True) -> Knowledge:
    kn = Knowledge(vault.db_path, create=create)
    if create and kn.available():
        from capitalizator.ops.wake import signer_wake

        kn.set_on_work(signer_wake(vault).notify)
    return kn
