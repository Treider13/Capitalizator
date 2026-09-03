"""bybit.json lives in secrets/. Backup refuses it. GET never carries seed."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.gateway.keys import load_keys
from capitalizator.ops.backup import BackupError, pack
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.user_keys import cred_present, live_cred_path, write_live_cred
from capitalizator.ops.vault import VaultError, init_vault


def test_write_live_cred_is_0600_and_gateway_reads_it(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    assert cred_present(vault) is False
    path = write_live_cred(vault, api_id="pub", seed="priv", mode="demo")
    assert path == live_cred_path(vault)
    assert path.parent == vault.secrets
    assert path.stat().st_mode & 0o077 == 0
    assert cred_present(vault) is True
    keys = load_keys(vault)
    assert keys is not None
    assert keys.api_key == "pub"
    assert keys.api_secret == "priv"
    assert keys.mode == "demo"


def test_write_live_cred_refuses_withdraw_blank_and_bad_mode(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    with pytest.raises(ValueError, match="withdraw"):
        write_live_cred(vault, api_id="ok", seed="withdraw-token")
    with pytest.raises(ValueError, match="id required"):
        write_live_cred(vault, api_id="  ", seed="priv")
    with pytest.raises(ValueError, match="mode"):
        write_live_cred(vault, api_id="ok", seed="priv", mode="mainnet")
    assert cred_present(vault) is False


def test_write_live_cred_refuses_symlink(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    path = live_cred_path(vault)
    path.symlink_to(target)
    with pytest.raises(VaultError, match="symlink"):
        write_live_cred(vault, api_id="pub", seed="priv")
    assert target.read_text(encoding="utf-8") == "{}"


def test_pack_refuses_secrets_with_key_file(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    write_live_cred(vault, api_id="pub", seed="priv-seed-not-in-pack")
    with pytest.raises(BackupError, match="secrets"):
        pack(vault, tmp_path / "bak")
    assert (vault.secrets / "bybit.json").is_file()
