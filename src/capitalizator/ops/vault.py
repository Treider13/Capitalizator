"""Freqtrade-style userdir: knowledge / tape / reports. Secrets never live here.

Laptop copy and VPS write the same tree. Empty dirs are honest, not a fake desk.
Walk never follows directory symlinks (pathlib rglob can).
"""

from __future__ import annotations

import os
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
    """List regular files only. Symlinks, fifos, and devices are a hard reject."""
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
            if not stat.S_ISREG(path.lstat().st_mode):
                raise VaultError(f"not a regular file: {path}")
            yield path


def _require_real_dir(path: Path, *, name: str) -> None:
    if path.is_symlink():
        raise VaultError(f"vault layer is a symlink: {name}")
    if path.exists() and not path.is_dir():
        raise VaultError(f"vault layer is not a directory: {name}")


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
    if vault.layout_path.is_symlink():
        raise VaultError("LAYOUT is a symlink")
    vault.layout_path.write_text(f"{LAYOUT_VERSION}\n", encoding="utf-8")
    readme = vault.secrets / "README.md"
    if not vault.secrets.exists():
        vault.secrets.mkdir()
    elif vault.secrets.is_symlink() or not vault.secrets.is_dir():
        raise VaultError("secrets/ exists and is not a real directory")
    if readme.is_symlink():
        raise VaultError("secrets/README.md is a symlink")
    if not readme.is_file():
        readme.write_text(
            "Сюда ключи не класть. Vault/sops на VPS. Этот каталог в бэкап не входит.\n",
            encoding="utf-8",
        )
    return vault


def load_vault(root: Path) -> Vault:
    vault = Vault(root=root.resolve())
    if vault.layout_path.is_symlink():
        raise VaultError("LAYOUT is a symlink")
    if not vault.layout_path.is_file():
        raise FileNotFoundError(f"not a vault: {vault.root} (missing LAYOUT)")
    version = vault.layout_path.read_text(encoding="utf-8").strip()
    if version != LAYOUT_VERSION:
        raise ValueError(f"unknown vault layout {version!r}")
    for folder in (vault.knowledge, vault.tape, vault.reports):
        _require_real_dir(folder, name=folder.name)
        if not folder.is_dir():
            raise FileNotFoundError(f"vault layer missing: {folder.name}")
    return vault
