"""Product freeze: user_mode in SQLite, never writes phase.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.ops.phase import phase_path, trading_mode
from capitalizator.ops.product import (
    USER_MODES,
    HelloRequired,
    hello_recorded,
    mark_hello,
    read_user_mode,
    set_user_mode,
)
from capitalizator.ops.vault import init_vault

PHASE = Path(__file__).resolve().parents[2] / "infra" / "phase.yaml"


def test_default_mode_is_off(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    assert read_user_mode(vault) == "off"
    assert USER_MODES == frozenset({"off", "learn", "demo", "live"})


def test_set_mode_requires_ack(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    with pytest.raises(ValueError, match="ack"):
        set_user_mode(vault, "demo", ack=False)


def test_demo_requires_a_green_hello(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    with pytest.raises(HelloRequired):
        set_user_mode(vault, "demo", ack=True)
    assert read_user_mode(vault) == "off"


def test_set_demo_does_not_write_phase_yaml(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    mark_hello(vault, ok=True)
    before = PHASE.read_bytes()
    yaml_mode = trading_mode()
    out = set_user_mode(vault, "demo", ack=True, ack_ts="2026-09-01T13:00:00Z")
    assert out["user_mode"] == "demo"
    assert read_user_mode(vault) == "demo"
    assert PHASE.read_bytes() == before
    assert trading_mode() == yaml_mode
    assert yaml_mode == "off"


def test_learn_needs_n_days(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    with pytest.raises(ValueError, match="learn_n_days"):
        set_user_mode(vault, "learn", ack=True)
    set_user_mode(vault, "learn", ack=True, learn_n_days=14)
    assert read_user_mode(vault) == "learn"


def test_unknown_mode_rejected(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    with pytest.raises(ValueError, match="unknown user_mode"):
        set_user_mode(vault, "grid", ack=True)


def test_hello_default_false(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "user")
    assert hello_recorded(vault) is False


def test_phase_yaml_path_unchanged() -> None:
    assert phase_path().resolve() == PHASE.resolve()
