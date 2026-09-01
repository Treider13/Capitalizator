"""Product freeze: user_mode in SQLite. Never writes infra/phase.yaml.

Laws: off|learn|demo|live. Bot does not advance phase.yaml.
24/7 is tape + journal + shadow. Orders only after a human ack on demo|live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.phase import phase_path, trading_mode
from capitalizator.ops.vault import Vault

USER_MODES = frozenset({"off", "learn", "demo", "live"})
META_USER_MODE = "user_mode"
META_LEARN_N = "learn_n_days"
META_LEARN_STARTED = "learn_started_at"
META_ACK = "mode_ack_ts"
META_HELLO = "testnet_hello"
DEFAULT_MODE = "off"


def user_mode_from_knowledge(knowledge: Knowledge) -> str:
    raw = knowledge.meta(META_USER_MODE)
    if raw is None:
        return DEFAULT_MODE
    if raw not in USER_MODES:
        raise ValueError(f"unknown user_mode: {raw!r}")
    return raw


def read_user_mode(vault: Vault) -> str:
    knowledge = open_knowledge(vault, create=False)
    try:
        if not knowledge.available():
            return DEFAULT_MODE
        return user_mode_from_knowledge(knowledge)
    finally:
        knowledge.close()


def set_user_mode(
    vault: Vault,
    mode: str,
    *,
    ack: bool,
    learn_n_days: int | None = None,
    ack_ts: str = "acked",
) -> dict[str, Any]:
    """Human switch. Requires ack. Does not write phase.yaml."""
    if mode not in USER_MODES:
        raise ValueError(f"unknown user_mode: {mode!r}")
    if not ack:
        raise ValueError("ack required")
    if mode == "learn":
        if learn_n_days is None or int(learn_n_days) < 1:
            raise ValueError("learn_n_days must be >= 1")
    phase_before = phase_path().read_bytes()
    trading_before = trading_mode()
    knowledge = open_knowledge(vault, create=True)
    try:
        knowledge.set_meta(META_USER_MODE, mode)
        knowledge.set_meta(META_ACK, ack_ts)
        if mode == "learn" and learn_n_days is not None:
            knowledge.set_meta(META_LEARN_N, str(int(learn_n_days)))
        out_mode = user_mode_from_knowledge(knowledge)
    finally:
        knowledge.close()
    if phase_path().read_bytes() != phase_before:
        raise RuntimeError("product must not write phase.yaml")
    if trading_mode() != trading_before:
        raise RuntimeError("product must not change trading_mode yaml")
    return {
        "user_mode": out_mode,
        "ack": True,
        "learn_n_days": learn_n_days,
        "trading_mode_yaml": trading_before,
    }


def hello_recorded(vault: Vault) -> bool:
    knowledge = open_knowledge(vault, create=False)
    try:
        if not knowledge.available():
            return False
        return knowledge.meta(META_HELLO) == "1"
    finally:
        knowledge.close()


def mark_hello(vault: Vault, *, ok: bool) -> None:
    knowledge = open_knowledge(vault, create=True)
    try:
        knowledge.set_meta(META_HELLO, "1" if ok else "0")
    finally:
        knowledge.close()


def default_universe_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "universe.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/universe.yaml not found")
