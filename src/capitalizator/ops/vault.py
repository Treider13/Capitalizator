"""Freqtrade-style userdir: knowledge / tape / reports. Secrets never live here.

Laptop copy and VPS write the same tree. Empty dirs are honest, not a fake desk.
Walk never follows directory symlinks (pathlib rglob can).
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

LAYERS = ("knowledge", "tape", "reports")
SECRETS_NAME = "secrets"
LAYOUT_NAME = "LAYOUT"
LAYOUT_VERSION = "1"
DB_NAME = "desk.sqlite"


class VaultError(ValueError):
    pass


@dataclass(frozen=True)
class Vault:
    root: Path

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def tape(self) -> Path:
        return self.root / "tape"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def secrets(self) -> Path:
        return self.root / SECRETS_NAME

    @property
    def db_path(self) -> Path:
        return self.knowledge / DB_NAME

    @property
    def layout_path(self) -> Path:
        return self.root / LAYOUT_NAME


def iter_regular_files(root: Path) -> Iterator[Path]:
    """List regular files only. Symlinks, fifos, devices, hardlinks are a hard reject."""
    if root.is_symlink():
        raise VaultError(f"symlink: {root}")
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in sorted(dirnames):
            path = base / name
            if path.is_symlink():
                raise VaultError(f"symlink: {path}")
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink():
                raise VaultError(f"symlink: {path}")
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode):
                raise VaultError(f"not a regular file: {path}")
            if st.st_nlink > 1:
                raise VaultError(f"hardlink: {path}")
            yield path


def open_regular(path: Path, *, flags: int = os.O_RDONLY) -> int:
    """Open a path that must still be a regular file. O_NOFOLLOW: no symlink swap."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    fd = os.open(path, flags | nofollow)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise VaultError(f"not a regular file: {path}")
        return fd
    except Exception:
        os.close(fd)
        raise


def same_inode(path: Path, st: os.stat_result) -> bool:
    try:
        cur = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISREG(cur.st_mode)
        and cur.st_ino == st.st_ino
        and cur.st_dev == st.st_dev
    )


def replace_if_same(tmp: Path, dest: Path, created: os.stat_result) -> None:
    """rename only our inode. After rename, dest must still be that inode.

    os.replace follows neither dest nor writes through it — but if *tmp* is
    swapped for a symlink after the check, rename *moves the symlink* onto dest.
    Then we unlink the dest *name* (the symlink), not the target.
    """
    if not same_inode(tmp, created):
        raise VaultError(f"tmp was replaced: {tmp}")
    os.replace(tmp, dest)
    if dest.is_symlink() or not same_inode(dest, created):
        if dest.is_symlink():
            dest.unlink()
        raise VaultError(f"replace produced unexpected inode: {dest}")


def read_regular_bytes(path: Path) -> bytes:
    fd = open_regular(path)
    try:
        parts: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            parts.append(chunk)
        return b"".join(parts)
    finally:
        os.close(fd)


def read_regular_text(path: Path) -> str:
    return read_regular_bytes(path).decode("utf-8", errors="ignore")


def write_regular_text(path: Path, text: str) -> None:
    """Write via mkstemp inode. Path.write_text follows a planted symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise VaultError(f"symlink: {path.parent}")
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    created = os.fstat(fd)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        replace_if_same(tmp, path, created)
    except Exception:
        if fd >= 0:
            os.close(fd)
        if same_inode(tmp, created):
            tmp.unlink()
        raise


def copy_regular(src: Path, dest: Path) -> None:
    """Copy via fds. shutil.copy2 follows a symlink planted after the walk."""
    fd = open_regular(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.parent.is_symlink():
        os.close(fd)
        raise VaultError(f"symlink: {dest.parent}")
    out_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent)
    )
    tmp = Path(tmp_name)
    created = os.fstat(out_fd)
    try:
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            os.write(out_fd, chunk)
        os.fsync(out_fd)
        os.close(out_fd)
        out_fd = -1
        replace_if_same(tmp, dest, created)
    except Exception:
        if out_fd >= 0:
            os.close(out_fd)
        if same_inode(tmp, created):
            tmp.unlink()
        raise
    finally:
        os.close(fd)


def _require_real_dir(path: Path, *, name: str) -> None:
    if path.is_symlink():
        raise VaultError(f"vault layer is a symlink: {name}")
    if path.exists() and not path.is_dir():
        raise VaultError(f"vault layer is not a directory: {name}")


def assert_no_symlink_components(root: Path, path: Path) -> None:
    """pathlib mkdir(exist_ok=True) follows a directory symlink. Refuse any link in the chain."""
    if root.is_symlink():
        raise VaultError(f"symlink: {root}")
    try:
        rel = path.relative_to(root)
    except ValueError as exc:
        raise VaultError(f"path escapes: {path}") from exc
    cur = root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise VaultError(f"symlink: {cur}")


def mkdir_real_parents(root: Path, directory: Path) -> None:
    """Create directory one name at a time. Do not follow a planted dir symlink."""
    if root.is_symlink() or not root.is_dir():
        raise VaultError(f"symlink: {root}")
    try:
        rel = directory.relative_to(root)
    except ValueError as exc:
        raise VaultError(f"path escapes: {directory}") from exc
    cur = root
    for part in rel.parts:
        nxt = cur / part
        if nxt.is_symlink():
            raise VaultError(f"symlink: {nxt}")
        if nxt.exists():
            if not nxt.is_dir():
                raise VaultError(f"not a directory: {nxt}")
        else:
            nxt.mkdir()
            if nxt.is_symlink() or not nxt.is_dir():
                raise VaultError(f"symlink: {nxt}")
        cur = nxt


def init_vault(root: Path) -> Vault:
    vault = Vault(root=root.resolve())
    if vault.root.exists() and vault.root.is_symlink():
        raise VaultError(f"vault root is a symlink: {vault.root}")
    vault.root.mkdir(parents=True, exist_ok=True)
    for folder in (vault.knowledge, vault.tape, vault.reports):
        if folder.exists() and (folder.is_symlink() or not folder.is_dir()):
            raise VaultError(
                f"vault layer exists and is not a real directory: {folder.name}"
            )
        folder.mkdir(exist_ok=True)
        if folder.is_symlink() or not folder.is_dir():
            raise VaultError(f"vault layer is not a real directory: {folder.name}")
        assert_no_symlink_components(vault.root, folder)
    if vault.layout_path.is_symlink():
        raise VaultError("LAYOUT is a symlink")
    write_regular_text(vault.layout_path, f"{LAYOUT_VERSION}\n")
    readme = vault.secrets / "README.md"
    if not vault.secrets.exists():
        vault.secrets.mkdir()
    if vault.secrets.is_symlink() or not vault.secrets.is_dir():
        raise VaultError("secrets/ exists and is not a real directory")
    if readme.is_symlink():
        raise VaultError("secrets/README.md is a symlink")
    if not readme.is_file():
        write_regular_text(
            readme,
            "Сюда ключи не класть. Vault/sops на VPS. Этот каталог в бэкап не входит.\n",
        )
    return vault


def load_vault(root: Path) -> Vault:
    vault = Vault(root=root.resolve())
    if vault.layout_path.is_symlink():
        raise VaultError("LAYOUT is a symlink")
    if not vault.layout_path.is_file():
        raise FileNotFoundError(f"not a vault: {vault.root} (missing LAYOUT)")
    version = read_regular_text(vault.layout_path).strip()
    if version != LAYOUT_VERSION:
        raise ValueError(f"unknown vault layout {version!r}")
    for folder in (vault.knowledge, vault.tape, vault.reports):
        _require_real_dir(folder, name=folder.name)
        if not folder.is_dir():
            raise FileNotFoundError(f"vault layer missing: {folder.name}")
        assert_no_symlink_components(vault.root, folder)
    return vault
