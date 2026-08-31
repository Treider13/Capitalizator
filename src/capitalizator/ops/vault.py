"""Freqtrade-style userdir: knowledge / tape / reports. Secrets never live here.

Laptop copy and VPS write the same tree. Empty dirs are honest, not a fake desk.
Walk never follows directory symlinks (pathlib rglob can).
"""

from __future__ import annotations

import errno
import os
import secrets
import stat
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
    """Open a regular file. os.open(path, O_NOFOLLOW) still follows a *parent* symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    dir_fd = open_real_dir_fd(path.parent, create=False)
    try:
        try:
            fd = os.open(path.name, flags | nofollow, dir_fd=dir_fd)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise VaultError(f"symlink: {path}") from exc
            raise
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise VaultError(f"not a regular file: {path}")
            if st.st_nlink > 1:
                raise VaultError(f"hardlink: {path}")
            return fd
        except Exception:
            os.close(fd)
            raise
    finally:
        os.close(dir_fd)


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


def open_real_dir_fd(directory: Path, *, create: bool = True) -> int:
    """Open directory via openat(O_NOFOLLOW). Path.mkdir and mkstemp(dir=) follow a swap.

    Fact: after reports/ is renamed and replaced with a symlink to outside/nested,
    tempfile.mkstemp(dir=reports/nested) writes into outside. A held dir_fd does not.
    """
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    flags = os.O_RDONLY | os.O_DIRECTORY
    abs_dir = Path(os.path.abspath(directory))
    parts = abs_dir.parts
    fd = os.open(parts[0], flags)
    try:
        for part in parts[1:]:
            try:
                nxt = os.open(part, flags | nofollow, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise VaultError(f"not a directory: {abs_dir}") from None
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                try:
                    nxt = os.open(part, flags | nofollow, dir_fd=fd)
                except OSError as exc:
                    # Linux: O_NOFOLLOW|O_DIRECTORY on a symlink is ENOTDIR, not ELOOP.
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise VaultError(f"symlink: {part}") from exc
                    raise
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise VaultError(f"symlink: {part}") from exc
                raise
            os.close(fd)
            fd = nxt
        return fd
    except Exception:
        os.close(fd)
        raise


def mkdtemp_dir_at(dir_fd: int, *, prefix: str, suffix: str) -> str:
    """Exclusive mkdirat. tempfile.mkdtemp(dir=parent) follows a swapped parent."""
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(8)}{suffix}"
        try:
            os.mkdir(name, 0o700, dir_fd=dir_fd)
            return name
        except FileExistsError:
            continue
    raise VaultError("mkdtemp_dir_at exhausted")


def remove_tree_at(dir_fd: int, name: str) -> None:
    """Remove name inside dir_fd. Never follow a symlink — unlink the name."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        os.unlink(name, dir_fd=dir_fd)
        return
    child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=dir_fd)
    try:
        for child in os.listdir(child_fd):
            remove_tree_at(child_fd, child)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=dir_fd)


def promote_dir_at(dir_fd: int, src_name: str, dest_name: str) -> None:
    """renameat staging → dest. Path.rename follows a swapped parent (Linux)."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    try:
        st = os.stat(dest_name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        os.rename(src_name, dest_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        return
    if stat.S_ISLNK(st.st_mode):
        raise VaultError(f"symlink: {dest_name}")
    if not stat.S_ISDIR(st.st_mode):
        raise VaultError(f"dest not a directory: {dest_name}")
    empty_fd = os.open(dest_name, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=dir_fd)
    try:
        if os.listdir(empty_fd):
            raise VaultError(f"dest not empty: {dest_name}")
    finally:
        os.close(empty_fd)
    os.rmdir(dest_name, dir_fd=dir_fd)
    os.rename(src_name, dest_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)


def mkstemp_at(dir_fd: int, *, prefix: str, suffix: str) -> tuple[int, str]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(8)}{suffix}"
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
                dir_fd=dir_fd,
            )
            return fd, name
        except FileExistsError:
            continue
    raise VaultError("mkstemp_at exhausted")


def replace_at(dir_fd: int, tmp_name: str, dest_name: str, created: os.stat_result) -> None:
    """renameat on a held directory fd. os.replace(tmp, dest) follows a parent symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise VaultError("O_NOFOLLOW required")
    chk = os.open(tmp_name, os.O_RDONLY | nofollow, dir_fd=dir_fd)
    try:
        st = os.fstat(chk)
        if not (
            stat.S_ISREG(st.st_mode)
            and st.st_ino == created.st_ino
            and st.st_dev == created.st_dev
        ):
            raise VaultError(f"tmp was replaced: {tmp_name}")
    finally:
        os.close(chk)
    os.replace(tmp_name, dest_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    dest_fd = -1
    try:
        dest_fd = os.open(dest_name, os.O_RDONLY | nofollow, dir_fd=dir_fd)
        st = os.fstat(dest_fd)
        if not (
            stat.S_ISREG(st.st_mode)
            and st.st_ino == created.st_ino
            and st.st_dev == created.st_dev
        ):
            raise VaultError(f"replace produced unexpected inode: {dest_name}")
    except (OSError, VaultError) as exc:
        try:
            os.unlink(dest_name, dir_fd=dir_fd)
        except OSError:
            pass
        if isinstance(exc, VaultError):
            raise
        raise VaultError(f"replace produced unexpected inode: {dest_name}") from exc
    finally:
        if dest_fd >= 0:
            os.close(dest_fd)


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


def write_regular_bytes(path: Path, data: bytes) -> None:
    """Write via a held parent dir_fd. tempfile.mkstemp(dir=) follows a swapped ancestor."""
    dir_fd = open_real_dir_fd(path.parent)
    fd = -1
    tmp_name: str | None = None
    try:
        fd, tmp_name = mkstemp_at(dir_fd, prefix=f".{path.name}.", suffix=".tmp")
        created = os.fstat(fd)
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        replace_at(dir_fd, tmp_name, path.name, created)
        tmp_name = None
    except Exception:
        if fd >= 0:
            os.close(fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=dir_fd)
            except OSError:
                pass
        raise
    finally:
        os.close(dir_fd)


def write_regular_text(path: Path, text: str) -> None:
    """Write via mkstemp inode. Path.write_text follows a planted symlink."""
    write_regular_bytes(path, text.encode("utf-8"))


def copy_regular(src: Path, dest: Path) -> None:
    """Copy via fds. shutil.copy2 follows a symlink planted after the walk."""
    dir_fd = open_real_dir_fd(dest.parent)
    src_fd = -1
    out_fd = -1
    tmp_name: str | None = None
    try:
        src_fd = open_regular(src)
        out_fd, tmp_name = mkstemp_at(dir_fd, prefix=f".{dest.name}.", suffix=".tmp")
        created = os.fstat(out_fd)
        while True:
            chunk = os.read(src_fd, 65536)
            if not chunk:
                break
            os.write(out_fd, chunk)
        os.fsync(out_fd)
        os.close(out_fd)
        out_fd = -1
        replace_at(dir_fd, tmp_name, dest.name, created)
        tmp_name = None
    except Exception:
        if out_fd >= 0:
            os.close(out_fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=dir_fd)
            except OSError:
                pass
        raise
    finally:
        if src_fd >= 0:
            os.close(src_fd)
        os.close(dir_fd)


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


def ensure_real_parent(directory: Path) -> Path:
    """Create directory without following any symlink. Unlike Path.mkdir(parents=True).

    Walk every ancestor, including ones that already exist. Stopping at the first
    existing dir misses a symlink *above* a nested name that pathlib already
    created inside the target (nested is a real directory; the leak is one name up).
    abspath, not resolve: resolve() follows the link and hides it.
    """
    cur = Path(os.path.abspath(directory))
    chain: list[Path] = []
    while True:
        chain.append(cur)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    for node in reversed(chain):
        if node.is_symlink():
            raise VaultError(f"symlink: {node}")
        if node.exists():
            if not node.is_dir():
                raise VaultError(f"not a directory: {node}")
            continue
        try:
            node.mkdir()
        except FileExistsError:
            pass
        if node.is_symlink() or not node.is_dir():
            raise VaultError(f"symlink: {node}")
    return chain[0]


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
            try:
                nxt.mkdir()
            except FileExistsError:
                pass
            if nxt.is_symlink() or not nxt.is_dir():
                raise VaultError(f"symlink: {nxt}")
        cur = nxt


def init_vault(root: Path) -> Vault:
    if root.is_symlink() and not root.exists():
        raise VaultError(f"vault root is a dangling symlink: {root}")
    vault = Vault(root=root.resolve())
    if vault.root.exists() and vault.root.is_symlink():
        raise VaultError(f"vault root is a symlink: {vault.root}")
    vault.root.mkdir(parents=True, exist_ok=True)
    for folder in (vault.knowledge, vault.tape, vault.reports):
        # exists() follows: a dangling layer symlink looks missing, then mkdir
        # raises FileExistsError instead of a vault refuse.
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
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
    if vault.secrets.is_symlink():
        raise VaultError("secrets/ exists and is not a real directory")
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
