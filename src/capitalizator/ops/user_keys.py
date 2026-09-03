"""Write and detect the live cred file. Console never imports signer.

Default path is `{userdir}/live.cred` at the vault root — not knowledge/tape/reports,
not secrets/. Backup does not pack this file. GET never echoes seed.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from capitalizator.ops.vault import Vault, VaultError, open_regular, write_regular_text

LIVE_CRED_NAME = "live.cred"
_MAX_FIELD = 256


def live_cred_path(vault: Vault) -> Path:
    """Do not Path.resolve() the filename: that follows a planted symlink."""
    return vault.root / LIVE_CRED_NAME


def cred_present(vault: Vault) -> bool:
    path = live_cred_path(vault)
    if path.is_symlink() or not path.is_file():
        return False
    try:
        st = path.stat()
    except OSError:
        return False
    return st.st_size > 0


def _one_field(name: str, raw: object) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{name} required")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise ValueError(f"{name} must be one line")
    if len(value) > _MAX_FIELD:
        raise ValueError(f"{name} too long")
    if "withdraw" in value.lower():
        raise ValueError("withdraw token refused")
    return value


def write_live_cred(vault: Vault, *, api_id: str, seed: str) -> Path:
    public = _one_field("id", api_id)
    private = _one_field("seed", seed)
    path = live_cred_path(vault)
    if path.is_symlink():
        raise VaultError(f"symlink: {path}")
    write_regular_text(path, f"id={public}\nseed={private}\n")
    fd = open_regular(path)
    try:
        os.fchmod(fd, 0o600)
        mode = stat.S_IMODE(os.fstat(fd).st_mode)
        if mode & 0o077:
            raise VaultError(f"cred file must be 0600: {path}")
    finally:
        os.close(fd)
    return path
