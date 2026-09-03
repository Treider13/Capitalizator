"""Write and detect the Bybit key file. Console never imports signer.

Path is `{userdir}/secrets/bybit.json` — same file the gateway reads.
Backup refuses a non-empty secrets/. GET never echoes the secret.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from capitalizator.ops.vault import Vault, VaultError, open_regular, write_regular_text

FILE_NAME = "bybit.json"
MODES = frozenset({"demo", "testnet", "live_sub", "live_main"})
_MAX_FIELD = 256


def live_cred_path(vault: Vault) -> Path:
    """Do not Path.resolve() the filename: that follows a planted symlink."""
    return vault.secrets / FILE_NAME


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


def write_live_cred(
    vault: Vault,
    *,
    api_id: str,
    seed: str,
    mode: str = "demo",
) -> Path:
    public = _one_field("id", api_id)
    private = _one_field("seed", seed)
    venue = str(mode or "demo").strip()
    if venue not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    path = live_cred_path(vault)
    if path.is_symlink():
        raise VaultError(f"symlink: {path}")
    body = json.dumps(
        {"api_key": public, "api_secret": private, "mode": venue},
        ensure_ascii=False,
    )
    write_regular_text(path, body + "\n")
    fd = open_regular(path)
    try:
        os.fchmod(fd, 0o600)
        mode_bits = stat.S_IMODE(os.fstat(fd).st_mode)
        if mode_bits & 0o077:
            raise VaultError(f"cred file must be 0600: {path}")
    finally:
        os.close(fd)
    return path
