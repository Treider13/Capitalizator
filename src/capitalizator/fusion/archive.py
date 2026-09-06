"""Crash-consistent Parquet archive: fsync/rename before deleting journal rows."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from capitalizator.fusion.store import Store, encode


def archive_events(store: Store, root: Path, before: float, batch: int) -> int:
    # Archive a contiguous ID prefix. Filtering by receipt time first could leave
    # newer interleaved actor events inside the deletion range and lose them.
    rows = store.rows("SELECT * FROM events ORDER BY id LIMIT ?", (batch,))
    if len(rows) < batch or any(row["received"] >= before for row in rows):
        return 0
    directory = root / "archive"
    directory.mkdir(exist_ok=True)
    digest = hashlib.sha256(encode(rows).encode()).hexdigest()
    destination = directory / f"events-{rows[0]['id']}-{rows[-1]['id']}-{digest[:16]}.parquet"
    temp = directory / ("." + uuid.uuid4().hex)
    try:
        pq.write_table(pa.Table.from_pylist(rows), temp, compression="zstd")
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, destination)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        with store.transaction() as db:
            manifest = {"path": destination.name, "sha256_rows": digest, "count": len(rows)}
            db.execute(
                "INSERT OR REPLACE INTO meta VALUES(?,?)",
                ("archive:" + destination.name, encode(manifest)),
            )
            db.execute("DELETE FROM events WHERE id>=? AND id<=?", (rows[0]["id"], rows[-1]["id"]))
    finally:
        temp.unlink(missing_ok=True)
    return len(rows)


def events(store: Store, root: Path) -> Any:
    """Yield durable actor-journal order without loading the full tape."""
    with store.snapshot() as db:
        yield from _snapshot_events(db, root)


def _snapshot_events(db: Any, root: Path) -> Any:
    manifests = db.execute("SELECT body FROM meta WHERE key LIKE 'archive:%'").fetchall()
    import json

    files = [json.loads(r["body"]) for r in manifests]
    files.sort(key=lambda r: int(r["path"].split("-")[1]))
    for manifest in files:
        path = root / "archive" / manifest["path"]
        rows = pq.read_table(path).to_pylist()
        if hashlib.sha256(encode(rows).encode()).hexdigest() != manifest["sha256_rows"]:
            raise ValueError("archive checksum mismatch")
        yield from rows
    cursor = 0
    while True:
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM events WHERE id>? ORDER BY id LIMIT 10000", (cursor,)
            ).fetchall()
        ]
        if not rows:
            break
        yield from rows
        cursor = rows[-1]["id"]
