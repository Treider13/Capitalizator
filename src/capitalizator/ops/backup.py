"""Pack / restore the vault. Secrets, symlinks, and key-shaped files are a hard reject.

Freqtrade: copy user_data, but a live SQLite file copy can tear; we use
sqlite3.Connection.backup (online backup API). Hummingbot: data/ ≠ conf/.
Default shutil.copytree follows symlink *content* — that inlines a key. Refuse links.
GitHub restic (#5143) and Borg: openat handle, not a second path after lstat.
GitHub sqlite/scrub.c: deleted cells stay in free pages until VACUUM/scrub.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from capitalizator.ops.knowledge import EMPTY_COUNTS, Knowledge, open_knowledge
from capitalizator.ops.vault import (
    DB_NAME,
    Vault,
    VaultError,
    copy_regular,
    ensure_real_parent,
    init_vault,
    iter_regular_files,
    load_vault,
    mkdtemp_dir_at,
    open_real_dir_fd,
    open_regular,
    promote_dir_at,
    read_regular_bytes,
    read_regular_text,
    remove_tree_at,
    write_regular_text,
)

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


def scan_secret_bytes(blob: bytes) -> list[str]:
    """Scan raw bytes. ASCII, case-fold, UTF-16 LE/BE.

    Fact: utf-16le and lowercase env-key needles packed (literals stay in tests).
    trufflehog (GitHub) scans UTF-16 LE/BE and matches keywords case-insensitive.
    gitleaks base64 decode defaults off — we do not invent that layer.
    """
    hits: list[str] = []
    blob_l = blob.lower()
    for needle in _needles():
        ascii_n = needle.encode("ascii")
        if ascii_n in blob or ascii_n.lower() in blob_l:
            hits.append(needle)
            continue
        folded = needle.lower()
        if any(
            needle.encode(enc) in blob or folded.encode(enc) in blob
            for enc in ("utf-16le", "utf-16be")
        ):
            hits.append(needle)
    return hits


def scan_secret_text(blob: str) -> list[str]:
    return scan_secret_bytes(blob.encode("utf-8", errors="surrogateescape"))


SKIP_NAMES = frozenset({".gitkeep", "README.md", "LAYOUT"})
REPORT_SUFFIX = frozenset({".md", ".txt"})
TAPE_SUFFIX = frozenset({".parquet"})
EPHEMERAL_SUFFIX = frozenset({".lock", ".tmp"})
SIDECARS = frozenset({"-wal", "-shm", "-journal"})


class BackupError(ValueError):
    pass


def _digest_size(path: Path) -> tuple[str, int]:
    try:
        fd = open_regular(path)
    except VaultError as exc:
        raise BackupError(str(exc)) from exc
    digest = hashlib.sha256()
    try:
        size = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
        return digest.hexdigest(), size
    finally:
        os.close(fd)


def _iter_files(root: Path) -> Iterable[Path]:
    try:
        for path in iter_regular_files(root):
            if path.suffix in EPHEMERAL_SUFFIX:
                continue
            yield path
    except VaultError as exc:
        raise BackupError(str(exc)) from exc


def assert_no_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise BackupError(f"symlink: {root}")
    if not root.is_dir():
        return
    try:
        list(iter_regular_files(root))
    except VaultError as exc:
        raise BackupError(str(exc)) from exc


def assert_layer_files(vault: Vault) -> None:
    assert_no_symlinks(vault.root)
    if vault.knowledge.is_dir():
        for path in _iter_files(vault.knowledge):
            if path.name != DB_NAME or path.parent != vault.knowledge:
                raise BackupError(f"unexpected file: {path}")
            if any(path.name.endswith(suf) for suf in SIDECARS):
                raise BackupError(f"sqlite sidecar: {path}")
    if vault.reports.is_dir():
        for path in _iter_files(vault.reports):
            if path.suffix not in REPORT_SUFFIX:
                raise BackupError(f"unexpected file: {path}")
    if vault.tape.is_dir():
        for path in _iter_files(vault.tape):
            if path.suffix not in TAPE_SUFFIX:
                raise BackupError(f"unexpected file: {path}")


def assert_no_secrets(vault: Vault) -> None:
    if vault.secrets.is_dir():
        extras = [p for p in vault.secrets.iterdir() if p.name not in SKIP_NAMES]
        if extras:
            names = ", ".join(sorted(p.name for p in extras))
            raise BackupError(f"secrets/ is not empty: {names}")
    assert_layer_files(vault)
    for layer in (vault.knowledge, vault.tape, vault.reports):
        if not layer.is_dir():
            continue
        for path in _iter_files(layer):
            try:
                data = read_regular_bytes(path)
            except VaultError as exc:
                raise BackupError(str(exc)) from exc
            hits = scan_secret_bytes(data)
            if hits:
                raise BackupError(f"secret pattern in {path}: {hits[0]}")
    try:
        knowledge = open_knowledge(vault, create=False)
    except ValueError as exc:
        raise BackupError(str(exc)) from exc
    hits: list[str] = []
    try:
        if not knowledge.verify_ok():
            raise BackupError("hash chain broken")
        hits = scan_secret_text(knowledge.all_text())
    finally:
        knowledge.close()
    if hits:
        raise BackupError(f"secret pattern in knowledge db: {hits[0]}")


def _parquet_stats(tape: Path) -> tuple[int, int]:
    if not tape.is_dir():
        return 0, 0
    files = [path for path in _iter_files(tape) if path.suffix in TAPE_SUFFIX]
    rows = 0
    for path in files:
        try:
            fd = open_regular(path)
        except VaultError as exc:
            raise BackupError(str(exc)) from exc
        with os.fdopen(fd, "rb") as fh:
            meta = pq.ParquetFile(fh).metadata
        if meta is None:
            raise BackupError(f"parquet metadata missing: {path}")
        rows += int(meta.num_rows)
    return len(files), rows


def _file_records(vault: Vault, *, with_tape: bool) -> dict[str, dict[str, int | str]]:
    records: dict[str, dict[str, int | str]] = {}
    layers = [vault.knowledge, vault.reports]
    if with_tape:
        layers.append(vault.tape)
    for layer in layers:
        if not layer.is_dir():
            continue
        for path in _iter_files(layer):
            rel = path.relative_to(vault.root).as_posix()
            digest, size = _digest_size(path)
            records[rel] = {"sha256": digest, "bytes": size}
    return records


def _copy_plain(src: Path, dest: Path, *, suffixes: frozenset[str]) -> None:
    if dest.is_symlink():
        raise BackupError(f"symlink: {dest}")
    try:
        ensure_real_parent(dest)
    except VaultError as exc:
        raise BackupError(str(exc)) from exc
    if dest.is_symlink() or not dest.is_dir():
        raise BackupError(f"symlink: {dest}")
    if not src.is_dir():
        return
    assert_no_symlinks(src)
    for path in _iter_files(src):
        if path.suffix not in suffixes:
            raise BackupError(f"unexpected file: {path}")
        rel = path.relative_to(src)
        if ".." in rel.parts:
            raise BackupError(f"unsafe path: {rel}")
        target = dest / rel
        try:
            copy_regular(path, target)
        except VaultError as exc:
            raise BackupError(str(exc)) from exc


def _safe_under(root: Path, rel: str) -> Path:
    raw = Path(rel)
    if raw.is_absolute() or ".." in raw.parts:
        raise BackupError(f"unsafe path: {rel}")
    root_r = root.resolve()
    path = (root_r / raw).resolve()
    if path != root_r and root_r not in path.parents:
        raise BackupError(f"path escapes backup: {rel}")
    return path


def _remove_staging(path: Path) -> None:
    """Never rmtree through a swapped parent. exists()/Path.rmtree follow."""
    try:
        parent_fd = open_real_dir_fd(path.parent, create=False)
    except VaultError:
        # Parent is a symlink (or gone). Last-component symlink: unlink the name.
        # Do not rmtree — that is how a swapped parent deletes a victim tree.
        if path.is_symlink():
            path.unlink()
        return
    try:
        remove_tree_at(parent_fd, path.name)
    finally:
        os.close(parent_fd)


def _make_staging(parent: Path, dest_name: str, *, suffix: str) -> Path:
    """Exclusive mkdirat. tempfile.mkdtemp(dir=parent) follows a swapped parent."""
    try:
        parent_fd = open_real_dir_fd(parent, create=True)
    except VaultError as exc:
        raise BackupError(str(exc)) from exc
    try:
        name = mkdtemp_dir_at(parent_fd, prefix=f".{dest_name}.", suffix=suffix)
        return parent / name
    finally:
        os.close(parent_fd)


def _mkdir_layers_at(parent_fd: int, staging_name: str) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise BackupError("O_NOFOLLOW required")
    staging_fd = os.open(
        staging_name, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=parent_fd
    )
    try:
        for name in ("knowledge", "reports", "tape"):
            os.mkdir(name, 0o755, dir_fd=staging_fd)
    finally:
        os.close(staging_fd)


def _stage_dest(dest: Path, *, suffix: str) -> tuple[int, str, Path]:
    """Hold dest.parent dir_fd, exclusive staging name. Path.rename follows a swap."""
    if dest.is_symlink():
        raise BackupError(f"symlink: {dest}")
    dest = dest.resolve()
    try:
        parent_fd = open_real_dir_fd(dest.parent, create=True)
    except VaultError as exc:
        raise BackupError(str(exc)) from exc
    try:
        staging_name = mkdtemp_dir_at(
            parent_fd, prefix=f".{dest.name}.", suffix=suffix
        )
    except Exception:
        os.close(parent_fd)
        raise
    return parent_fd, staging_name, dest.parent / staging_name


def _knowledge_counts(vault: Vault) -> dict[str, int]:
    try:
        knowledge = open_knowledge(vault, create=False)
    except ValueError as exc:
        raise BackupError(str(exc)) from exc
    try:
        if not knowledge.verify_ok():
            if not knowledge.integrity_ok():
                raise BackupError("integrity_check failed")
            raise BackupError("hash chain broken")
        return knowledge.counts()
    finally:
        knowledge.close()


def pack(
    vault: Vault,
    dest: Path,
    *,
    with_tape: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    load_vault(vault.root)
    assert_no_secrets(vault)
    parent_fd, staging_name, staging = _stage_dest(dest, suffix=".partial")
    dest = dest.resolve()
    try:
        _mkdir_layers_at(parent_fd, staging_name)
        write_regular_text(staging / "LAYOUT", "1\n")
        if vault.db_path.is_symlink():
            raise BackupError(f"symlink: {vault.db_path}")
        if vault.db_path.is_file():
            try:
                kn = Knowledge(vault.db_path, create=False)
            except ValueError as exc:
                raise BackupError(str(exc)) from exc
            try:
                kn.snapshot_to(staging / "knowledge" / DB_NAME)
            finally:
                kn.close()
            try:
                dest_kn = Knowledge(staging / "knowledge" / DB_NAME, create=False)
            except ValueError as exc:
                raise BackupError(str(exc)) from exc
            try:
                if not dest_kn.verify_ok():
                    if not dest_kn.integrity_ok():
                        raise BackupError("integrity_check failed")
                    raise BackupError("hash chain broken")
                counts = dest_kn.counts()
            finally:
                dest_kn.close()
        else:
            counts = dict(EMPTY_COUNTS)
        _copy_plain(vault.reports, staging / "reports", suffixes=REPORT_SUFFIX)
        if with_tape:
            _copy_plain(vault.tape, staging / "tape", suffixes=TAPE_SUFFIX)
        parquet_files, parquet_rows = _parquet_stats(staging / "tape") if with_tape else (0, 0)
        packed = Vault(root=staging)
        files = _file_records(packed, with_tape=with_tape)
        stamp = (now or datetime.now(UTC)).isoformat()
        manifest = {
            "schema": 1,
            "created": stamp,
            "layers": ["knowledge", "reports"] + (["tape"] if with_tape else []),
            "files": files,
            "counts": {
                **counts,
                "parquet_files": parquet_files,
                "parquet_rows": parquet_rows,
            },
            "hash_chain_ok": True,
            "secrets_excluded": True,
        }
        write_regular_text(
            staging / "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        verify_backup(staging)
        try:
            promote_dir_at(parent_fd, staging_name, dest.name)
        except VaultError as exc:
            raise BackupError(str(exc)) from exc
        staging_name = ""
    except Exception:
        if staging_name:
            try:
                remove_tree_at(parent_fd, staging_name)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_fd)
    return manifest


def _require_manifest(backup: Path) -> dict[str, Any]:
    path = backup / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise BackupError("manifest.json missing")
    try:
        raw = json.loads(read_regular_text(path))
    except VaultError as exc:
        raise BackupError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise BackupError("manifest must be an object")
    return raw


def _check_listed_files(root: Path, files: dict[str, Any]) -> None:
    for rel in files:
        _safe_under(root, str(rel))
    present = {
        p.relative_to(root).as_posix()
        for p in _iter_files(root)
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
        path = _safe_under(root, str(rel))
        if not isinstance(meta, dict):
            raise BackupError(f"bad file record: {rel}")
        if path.is_symlink() or not path.is_file():
            raise BackupError(f"missing listed file: {rel}")
        digest, size = _digest_size(path)
        if digest != meta.get("sha256"):
            raise BackupError(f"sha256 mismatch: {rel}")
        if size != meta.get("bytes"):
            raise BackupError(f"size mismatch: {rel}")


def verify_backup(backup: Path) -> dict[str, Any]:
    backup = backup.resolve()
    assert_no_symlinks(backup)
    manifest = _require_manifest(backup)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BackupError("manifest.files missing")
    _check_listed_files(backup, files)
    vault = load_vault(backup)
    assert_no_secrets(vault)
    counts = _knowledge_counts(vault)
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
    """Copy listed files only, on a staging dir, then rename. copytree is gone.

    Python shutil.copytree(symlinks=False) *inlines* symlink targets. A failed
    copy into dest used to leave a dirty tree (and a leaked file).
    """
    manifest = verify_backup(backup)
    if dest.is_symlink():
        raise BackupError(f"symlink: {dest}")
    dest = dest.resolve()
    if dest.exists() and not dest.is_dir():
        raise BackupError(f"restore dest not a directory: {dest}")
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"restore dest not empty: {dest}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BackupError("manifest.files missing")
    parent_fd, staging_name, staging = _stage_dest(dest, suffix=".restore")
    dest = dest.resolve()
    try:
        _mkdir_layers_at(parent_fd, staging_name)
        layout_src = backup / "LAYOUT"
        if layout_src.is_symlink() or not layout_src.is_file():
            raise BackupError("LAYOUT missing or symlink")
        try:
            copy_regular(layout_src, staging / "LAYOUT")
            for rel in files:
                copy_regular(_safe_under(backup, str(rel)), _safe_under(staging, str(rel)))
        except VaultError as exc:
            raise BackupError(str(exc)) from exc
        _check_listed_files(staging, files)
        vault = init_vault(staging)
        got = _knowledge_counts(vault)
        expect = manifest.get("counts")
        if not isinstance(expect, dict):
            raise BackupError("manifest.counts missing")
        for key in ("hash_links", "episodes", "reports"):
            if int(expect.get(key, -1)) != got[key]:
                raise BackupError(f"restore count mismatch {key}")
        if "tape" in manifest.get("layers", []):
            files_n, rows_n = _parquet_stats(vault.tape)
            if int(expect.get("parquet_files", -1)) != files_n:
                raise BackupError("restore parquet file count mismatch")
            if int(expect.get("parquet_rows", -1)) != rows_n:
                raise BackupError("restore parquet row count mismatch")
        try:
            promote_dir_at(parent_fd, staging_name, dest.name)
        except VaultError as exc:
            raise BackupError(str(exc)) from exc
        staging_name = ""
    except Exception:
        if staging_name:
            try:
                remove_tree_at(parent_fd, staging_name)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_fd)
    return load_vault(dest)


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
