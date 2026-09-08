"""Online SQLite snapshot plus exactly its immutable archive manifests; no signing keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from capitalizator.fusion.archive import read_archive


def backup(root: Path, destination: Path) -> dict[str, str]:
    if destination.exists():
        raise ValueError("backup destination must be new")
    source = root / "fusion.sqlite3"
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.mkdir(parents=True, mode=0o700)
    database = destination / "fusion.sqlite3"
    # Connection's context manager commits/rolls back; it does not close handles.
    # Close and checkpoint before hashing or publishing the backup's file manifest.
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(database)) as dst:
            src.backup(dst, pages=256)
            manifests = [
                json.loads(r[0])
                for r in dst.execute("SELECT body FROM meta WHERE key LIKE 'archive:%'")
            ]
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup SQLite integrity check failed")
    (destination / "archive").mkdir()
    for manifest in manifests:
        name = manifest["path"]
        if Path(name).name != name:
            raise ValueError("invalid archive path")
        shutil.copyfile(root / "archive" / name, destination / "archive" / name)
        # A checksum of a corrupt copy is not proof that it matches the ledger.
        read_archive(destination / "archive" / name, manifest)
    for name in ("config.json", "news_sources.json"):
        if (root / name).is_file():
            shutil.copyfile(root / name, destination / name)
    checksums = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                os.fsync(stream.fileno())
            checksums[str(path.relative_to(destination))] = checksum
    manifest_path = destination / "sha256.json"
    with manifest_path.open("x") as stream:
        json.dump(checksums, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return checksums


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--userdir", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(backup(args.userdir, args.dest)))


if __name__ == "__main__":
    main()
