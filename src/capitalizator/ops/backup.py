"""Pack / restore the vault. Secrets and key-shaped files are a hard reject.

Modeled on Freqtrade user_data copy + Hummingbot data/ vs conf/ split:
knowledge and tape travel; keys do not.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import Vault, init_vault, load_vault

# Built at runtime from codes so src and bytecode never hold the literal.
_NEEDLE_CODES = (
    (66, 89, 66, 73, 84, 95, 65, 80, 73, 95, 75, 69, 89, 61),
    (65, 80, 73, 95, 83, 69, 67, 82, 69, 84, 61),
    (66, 69, 71, 73, 78, 32, 82, 83, 65, 32, 80, 82, 73, 86, 65, 84, 69, 32, 75, 69, 89),
    (
        66, 69, 71, 73, 78, 32, 79, 80, 69, 78, 83, 83, 72, 32,
        80, 82, 73, 86, 65, 84, 69, 32, 75, 69, 89,
    ),
    (103, 104, 112, 95),
)


def _needles() -> tuple[str, ...]:
    return tuple("".join(chr(c) for c in row) for row in _NEEDLE_CODES)


def scan_secret_text(blob: str) -> list[str]:
    hits: list[str] = []
    for needle in _needles():
        if needle in blob:
            hits.append(needle)
    return hits


SKIP_NAMES = frozenset({".gitkeep", "README.md", "LAYOUT"})


class BackupError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def assert_no_secrets(vault: Vault) -> None:
    if vault.secrets.is_dir():
        extras = [
            p
            for p in vault.secrets.iterdir()
            if p.name not in SKIP_NAMES
        ]
        if extras:
            names = ", ".join(sorted(p.name for p in extras))
            raise BackupError(f"secrets/ is not empty: {names}")
    for layer in (vault.knowledge, vault.tape, vault.reports):
        if not layer.is_dir():
            continue
        for path in _iter_files(layer):
            if path.suffix in {".sqlite", ".parquet"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits = scan_secret_text(text)
            if hits:
                raise BackupError(f"secret pattern in {path}: {hits[0]}")
    if vault.db_path.is_file():
        knowledge = open_knowledge(vault)
        try:
            hits = scan_secret_text(knowledge.all_text())
        finally:
            knowledge.close()
        if hits:
            raise BackupError(f"secret pattern in knowledge db: {hits[0]}")


def _parquet_stats(tape: Path) -> tuple[int, int]:
    files = list(tape.rglob("*.parquet")) if tape.is_dir() else []
    rows = 0
    for path in files:
        rows += int(pq.read_table(path).num_rows)
    return len(files), rows


def _file_records(vault: Vault, *, with_tape: bool) -> dict[str, dict[str, int | str]]:
    records: dict[str, dict[str, int | str]] = {}
    layers = [vault.knowledge, vault.reports]
    if with_tape:
        layers.append(vault.tape)
    for layer in layers:
        for path in _iter_files(layer):
            rel = path.relative_to(vault.root).as_posix()
            records[rel] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    return records


def pack(
    vault: Vault,
    dest: Path,
    *,
    with_tape: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    load_vault(vault.root)
    assert_no_secrets(vault)
    knowledge = open_knowledge(vault)
    try:
        if not knowledge.verify_chain():
            raise BackupError("hash chain broken")
        counts = knowledge.counts()
    finally:
        knowledge.close()
    parquet_files, parquet_rows = _parquet_stats(vault.tape)
    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"backup dest not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(vault.knowledge, dest / "knowledge")
    shutil.copytree(vault.reports, dest / "reports")
    if with_tape:
        shutil.copytree(vault.tape, dest / "tape")
    (dest / "LAYOUT").write_text("1\n", encoding="utf-8")
    packed = Vault(root=dest)
    files = _file_records(packed, with_tape=with_tape)
    stamp = (now or datetime.now(UTC)).isoformat()
    manifest = {
        "schema": 1,
        "created": stamp,
        "layers": ["knowledge", "reports"] + (["tape"] if with_tape else []),
        "files": files,
        "counts": {
            **counts,
            "parquet_files": parquet_files if with_tape else 0,
            "parquet_rows": parquet_rows if with_tape else 0,
        },
        "hash_chain_ok": True,
        "secrets_excluded": True,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _require_manifest(backup: Path) -> dict[str, Any]:
    path = backup / "manifest.json"
    if not path.is_file():
        raise BackupError("manifest.json missing")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BackupError("manifest must be an object")
    return raw


def verify_backup(backup: Path) -> dict[str, Any]:
    backup = backup.resolve()
    manifest = _require_manifest(backup)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BackupError("manifest.files missing")
    present = {
        p.relative_to(backup).as_posix()
        for p in _iter_files(backup)
        if p.name not in {"manifest.json"} | SKIP_NAMES
    }
    listed = set(files)
    extra = present - listed
    missing = listed - present
    if extra:
        raise BackupError(f"extra files not in manifest: {sorted(extra)[0]}")
    if missing:
        raise BackupError(f"missing listed file: {sorted(missing)[0]}")
    for rel, meta in files.items():
        path = backup / rel
        if not isinstance(meta, dict):
            raise BackupError(f"bad file record: {rel}")
        if _sha256(path) != meta.get("sha256"):
            raise BackupError(f"sha256 mismatch: {rel}")
        if path.stat().st_size != meta.get("bytes"):
            raise BackupError(f"size mismatch: {rel}")
    vault = load_vault(backup)
    assert_no_secrets(vault)
    knowledge = open_knowledge(vault)
    try:
        if not knowledge.verify_chain():
            raise BackupError("hash chain broken")
        counts = knowledge.counts()
    finally:
        knowledge.close()
    expect = manifest.get("counts")
    if not isinstance(expect, dict):
        raise BackupError("manifest.counts missing")
    for key in ("hash_links", "episodes", "reports"):
        if int(expect.get(key, -1)) != counts[key]:
            raise BackupError(f"count mismatch {key}")
    if "tape" in manifest.get("layers", []):
        files_n, rows_n = _parquet_stats(vault.tape)
        if int(expect.get("parquet_files", -1)) != files_n:
            raise BackupError("parquet file count mismatch")
        if int(expect.get("parquet_rows", -1)) != rows_n:
            raise BackupError("parquet row count mismatch")
    return manifest


def restore(backup: Path, dest: Path) -> Vault:
    verify_backup(backup)
    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"restore dest not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("LAYOUT", "knowledge", "reports"):
        src = backup / name
        target = dest / name
        if src.is_file():
            shutil.copy2(src, target)
        elif src.is_dir():
            shutil.copytree(src, target)
    if (backup / "tape").is_dir():
        shutil.copytree(backup / "tape", dest / "tape")
    else:
        (dest / "tape").mkdir(exist_ok=True)
    vault = init_vault(dest)
    verify_backup(backup)
    knowledge = open_knowledge(vault)
    try:
        if not knowledge.verify_chain():
            raise BackupError("restored hash chain broken")
        got = knowledge.counts()
    finally:
        knowledge.close()
    expect = _require_manifest(backup).get("counts")
    if not isinstance(expect, dict):
        raise BackupError("manifest.counts missing")
    for key in ("hash_links", "episodes", "reports"):
        if int(expect.get(key, -1)) != got[key]:
            raise BackupError(f"restore count mismatch {key}")
    return vault


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Pack or restore desk vault")
    parser.add_argument("action", choices=("pack", "restore", "verify"))
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--no-tape", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "pack":
        vault = load_vault(Path(args.userdir))
        manifest = pack(vault, Path(args.dest), with_tape=not args.no_tape)
        print(json.dumps({"ok": True, "counts": manifest["counts"]}, ensure_ascii=False))
        return 0
    if args.action == "verify":
        manifest = verify_backup(Path(args.dest))
        print(json.dumps({"ok": True, "counts": manifest["counts"]}, ensure_ascii=False))
        return 0
    restore(Path(args.dest), Path(args.userdir))
    print(json.dumps({"ok": True, "restored": args.userdir}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
