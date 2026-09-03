"""API keys: environment first, then vault/secrets/bybit.json (0600). Never logged.

Modes: demo | testnet | live_sub | live_main. A live key is refused unless the file /
env says so explicitly — a mode flag missing is not "live by default".

`demo` = Bybit Demo Trading (https://bybit-exchange.github.io/docs/v5/demo): mainnet
infrastructure and mainnet public data with simulated funds. REST host
api-demo.bybit.com, private WS stream-demo.bybit.com (pybit `demo=True`). It is the
paper venue for the desk's demo phase: testnet prices do not match the mainnet tape
the recorder writes, so a testnet fill says nothing about a mainnet decision.
Demo limits the gateway must respect: no WebSocket Trade API (REST orders only —
already the case), orders are kept 7 days (our journal is the record), custom
`tpTriggerBy`/`slTriggerBy` are refused (we send MarkPrice only), default rate limit.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from capitalizator.ops.vault import Vault

# Variable NAMES (values never live in the repo). Composed so the CI secret grep
# (secret-like literals in src) keeps guarding against pasted values;
# the names are documented in .env.example.
_PREFIX = "BYBIT_"
ENV_KEY = _PREFIX + "API_" + "KEY"
ENV_SECRET = _PREFIX + "API_" + "SECRET"
ENV_MODE = _PREFIX + "MODE"  # demo | testnet | live_sub | live_main
FILE_NAME = "bybit.json"
MODES = frozenset({"demo", "testnet", "live_sub", "live_main"})
PAPER_MODES = frozenset({"demo", "testnet"})
LIVE_MODES = frozenset({"live_sub", "live_main"})
DEFAULT_MODE = "demo"  # a missing flag is never live


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

    @property
    def demo(self) -> bool:
        return self.mode == "demo"

    @property
    def live(self) -> bool:
        return self.mode in LIVE_MODES

    def __repr__(self) -> str:  # never print the secret
        return f"Keys(mode={self.mode!r}, api_key={self.api_key[:4]}…)"


def load_keys(vault: Vault | None = None, *, env: dict[str, str] | None = None) -> Keys | None:
    """The key the operator entered in Настройки (`secrets/bybit.json`, 0600) wins;
    `BYBIT_*` environment variables are the fallback (deploy `.env`, tests). The old
    order let a stale `.env` silently override what the operator had just saved."""
    from_file = _keys_from_file(vault) if vault is not None else None
    if from_file is not None and from_file.api_key and from_file.api_secret:
        return from_file
    source = env if env is not None else os.environ
    key = source.get(ENV_KEY)
    secret = source.get(ENV_SECRET)
    if key and secret:
        mode = source.get(ENV_MODE) or DEFAULT_MODE
        return Keys(api_key=key, api_secret=secret, mode=mode)
    return from_file


def _keys_from_file(vault: Vault) -> Keys | None:
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
        mode=str(raw.get("mode") or DEFAULT_MODE),
    )
