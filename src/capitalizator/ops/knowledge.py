"""SQLite knowledge base. Same idea as Freqtrade tradesv3.sqlite — portable file.

Empty tables are honest. Does not read keys. Does not open size.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from capitalizator.memory.hashlog import GENESIS, HashChain, HashLink
from capitalizator.ops.daily_map_report import _ADVICE
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


class Knowledge:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._cx = sqlite3.connect(path)
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        self._cx.executescript(SCHEMA)
        self._cx.execute(
            "INSERT OR IGNORE INTO meta(k, v) VALUES ('schema', '1')"
        )
        self._cx.commit()

    def close(self) -> None:
        self._cx.close()

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("hash_links", "episodes", "reports"):
            row = self._cx.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"])
        return out

    def append_link(self, payload: str) -> HashLink:
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
        return link

    def links(self) -> list[HashLink]:
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
        required = ("trade_id", "mode", "zone_id", "gesture", "fill", "slip", "fees", "r")
        missing = [k for k in required if k not in row]
        if missing:
            raise ValueError(f"episode missing: {missing}")
        if row["mode"] not in EPISODE_MODES:
            raise ValueError(f"episode.mode must be shadow|demo, got {row['mode']!r}")
        fill = row["fill"]
        if isinstance(fill, datetime):
            fill_text = fill.isoformat()
        else:
            fill_text = str(fill)
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

    def episodes(self) -> list[dict[str, str]]:
        rows = self._cx.execute(
            "SELECT trade_id, mode, zone_id, gesture, fill, slip, fees, r "
            "FROM episodes ORDER BY fill"
        ).fetchall()
        return [{k: str(row[k]) for k in row.keys()} for row in rows]

    def save_report(self, *, day: str, kind: str, body: str) -> None:
        if _ADVICE.search(body) or _ADVICE.search(day) or _ADVICE.search(kind):
            raise ValueError("report must not advise")
        self._cx.execute(
            "INSERT OR REPLACE INTO reports(day, kind, body) VALUES (?, ?, ?)",
            (day, kind, body),
        )
        self._cx.commit()

    def report(self, *, day: str, kind: str = "map") -> str | None:
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
        for row in self._cx.execute("SELECT day, kind, body FROM reports"):
            parts.extend(str(row[k]) for k in row.keys())
        for link in self.links():
            parts.append(link.payload)
        return "\n".join(parts)

    def latest_report(self) -> dict[str, str] | None:
        row = self._cx.execute(
            "SELECT day, kind, body FROM reports ORDER BY day DESC, kind LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {"day": str(row["day"]), "kind": str(row["kind"]), "body": str(row["body"])}


def open_knowledge(vault: Vault) -> Knowledge:
    return Knowledge(vault.db_path)
