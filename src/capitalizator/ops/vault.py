"""Freqtrade-style userdir: knowledge / tape / reports. Secrets never live here.

Laptop copy and VPS write the same tree. Empty dirs are honest, not a fake desk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LAYERS = ("knowledge", "tape", "reports")
SECRETS_NAME = "secrets"
LAYOUT_NAME = "LAYOUT"
LAYOUT_VERSION = "1"
DB_NAME = "desk.sqlite"


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


def init_vault(root: Path) -> Vault:
    vault = Vault(root=root.resolve())
    vault.root.mkdir(parents=True, exist_ok=True)
    for folder in (vault.knowledge, vault.tape, vault.reports):
        folder.mkdir(exist_ok=True)
    vault.layout_path.write_text(f"{LAYOUT_VERSION}\n", encoding="utf-8")
    readme = vault.secrets / "README.md"
    if not vault.secrets.exists():
        vault.secrets.mkdir()
    if not readme.is_file():
        readme.write_text(
            "Сюда ключи не класть. Vault/sops на VPS. Этот каталог в бэкап не входит.\n",
            encoding="utf-8",
        )
    return vault


def load_vault(root: Path) -> Vault:
    vault = Vault(root=root.resolve())
    if not vault.layout_path.is_file():
        raise FileNotFoundError(f"not a vault: {vault.root} (missing LAYOUT)")
    version = vault.layout_path.read_text(encoding="utf-8").strip()
    if version != LAYOUT_VERSION:
        raise ValueError(f"unknown vault layout {version!r}")
    for folder in (vault.knowledge, vault.tape, vault.reports):
        if not folder.is_dir():
            raise FileNotFoundError(f"vault layer missing: {folder.name}")
    return vault
