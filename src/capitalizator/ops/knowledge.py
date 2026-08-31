"""SQLite knowledge base. Same idea as Freqtrade tradesv3.sqlite — portable file.

Empty tables are honest. Does not read keys. Does not open size.
Open with create=False never writes a missing file (pack/verify must not invent a db).
Writes take BEGIN IMMEDIATE. Snapshot uses sqlite3 backup API, not a raw file copy.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from capitalizator.memory.hashlog import GENESIS, HashChain, HashLink
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.vault import Vault

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
"""

EPISODE_MODES = frozenset({"shadow", "demo"})
EMPTY_COUNTS = {"hash_links": 0, "episodes": 0, "reports": 0}


class Knowledge:
    def __init__(self, path: Path, *, create: bool = True) -> None:
        self.path = path
        if not path.is_file() and not create:
            self._cx: sqlite3.Connection | None = None
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._cx = sqlite3.connect(path, timeout=5.0)
        self._cx.isolation_level = None
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        self._cx.executescript(SCHEMA)
        self._cx.execute("INSERT OR IGNORE INTO meta(k, v) VALUES ('schema', '1')")

    def close(self) -> None:
        if self._cx is not None:
            self._cx.close()
            self._cx = None

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
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        dst = sqlite3.connect(dest, timeout=5.0)
        try:
            self._cx.backup(dst)
            row = dst.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]) != "ok":
                raise ValueError("integrity_check failed after snapshot")
        finally:
            dst.close()

    def append_link(self, payload: str) -> HashLink:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        self._cx.execute("BEGIN IMMEDIATE")
        try:
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

    def append_episode(self, row: Mapping[str, Any]) -> None:
        if self._cx is None:
            raise FileNotFoundError("no knowledge db")
        required = ("trade_id", "mode", "zone_id", "gesture", "fill", "slip", "fees", "r")
        missing = [k for k in required if k not in row]
        if missing:
            raise ValueError(f"episode missing: {missing}")
        if row["mode"] not in EPISODE_MODES:
            raise ValueError(f"episode.mode must be shadow|demo, got {row['mode']!r}")
        fill = row["fill"]
        fill_text = fill.isoformat() if isinstance(fill, datetime) else str(fill)
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            self._cx.execute(
                """
                INSERT INTO episodes(trade_id, mode, zone_id, gesture, fill, slip, fees, r)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row["trade_id"]),
                    str(row["mode"]),
                    str(row["zone_id"]),
                    str(row["gesture"]),
                    fill_text,
                    str(row["slip"]),
                    str(row["fees"]),
                    str(row["r"]),
                ),
            )
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


def open_knowledge(vault: Vault, *, create: bool = True) -> Knowledge:
    return Knowledge(vault.db_path, create=create)
