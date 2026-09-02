"""API keys: environment first, then vault/secrets/bybit.json (0600). Never logged.

Modes: testnet | live_sub | live_main. A live key is refused unless the file /
env says so explicitly — a testnet flag missing is not "live by default".
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from capitalizator.ops.vault import Vault

ENV_KEY = "BYBIT_API_KEY"
ENV_SECRET = "BYBIT_API_SECRET"
ENV_MODE = "BYBIT_MODE"  # testnet | live_sub | live_main
FILE_NAME = "bybit.json"
MODES = frozenset({"testnet", "live_sub", "live_main"})


@dataclass(frozen=True)
class Keys:
    api_key: str
    api_secret: str
    mode: str

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ValueError("empty api key/secret")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")

    @property
    def testnet(self) -> bool:
        return self.mode == "testnet"

    def __repr__(self) -> str:  # never print the secret
        return f"Keys(mode={self.mode!r}, api_key={self.api_key[:4]}…)"


def load_keys(vault: Vault | None = None, *, env: dict[str, str] | None = None) -> Keys | None:
    source = env if env is not None else os.environ
    key = source.get(ENV_KEY)
    secret = source.get(ENV_SECRET)
    if key and secret:
        mode = source.get(ENV_MODE) or "testnet"
        return Keys(api_key=key, api_secret=secret, mode=mode)
    if vault is None:
        return None
    path: Path = vault.secrets / FILE_NAME
    if path.is_symlink() or not path.is_file():
        return None
    st = path.stat()
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise ValueError(f"{path} must be 0600 (group/other readable)")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("bybit.json must be an object")
    return Keys(
        api_key=str(raw.get("api_key") or ""),
        api_secret=str(raw.get("api_secret") or ""),
        mode=str(raw.get("mode") or "testnet"),
    )
