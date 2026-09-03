"""Load exchange credentials from a regular file. Desk never imports this.

File fields: `id=` (public) and `seed=` (private). Mode must be 0600.
Symlink / FIFO / hardlink / world-readable — refuse.
Does not read KEY/SECRET/TOKEN/PASS from the environment.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from capitalizator.ops.vault import VaultError, open_regular


@dataclass(frozen=True)
class Cred:
    public: str
    seed: str


def cred_path_from_env() -> Path | None:
    raw = os.getenv("CAPITALIZATOR_CRED_FILE")
    if raw is None or not str(raw).strip():
        return None
    return Path(str(raw).strip())


def default_cred_file(userdir: Path) -> Path:
    """Env override, else `{userdir}/live.cred` written by Chronos."""
    env = cred_path_from_env()
    if env is not None:
        return env
    return Path(userdir) / "live.cred"


def load_cred(path: Path) -> Cred:
    if path.is_symlink():
        raise VaultError(f"symlink: {path}")
    fd = open_regular(path)
    try:
        st = os.fstat(fd)
        if st.st_nlink > 1:
            raise VaultError(f"hardlink: {path}")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise VaultError(f"cred file must be 0600: {path}")
        raw = os.read(fd, 8192).decode("utf-8")
    finally:
        os.close(fd)
    public = ""
    seed = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise VaultError("cred line must be field=value")
        field, value = line.split("=", 1)
        field = field.strip().lower()
        value = value.strip()
        if field == "id":
            public = value
        elif field == "seed":
            seed = value
        else:
            raise VaultError(f"unknown cred field: {field}")
    if not public or not seed:
        raise VaultError("cred file needs id= and seed=")
    if "withdraw" in public.lower() or "withdraw" in seed.lower():
        raise VaultError("withdraw token refused")
    return Cred(public=public, seed=seed)
