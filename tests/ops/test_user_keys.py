"""live.cred lives at the vault root. Backup and GET never carry seed."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.ops.backup import pack
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.user_keys import cred_present, live_cred_path, write_live_cred
from capitalizator.ops.vault import VaultError, init_vault
from capitalizator.signer.cred import load_cred


def test_write_live_cred_is_0600(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    assert cred_present(vault) is False
    path = write_live_cred(vault, api_id="pub", seed="priv")
    assert path == live_cred_path(vault)
    assert path.parent == vault.root
    assert path.stat().st_mode & 0o077 == 0
    assert cred_present(vault) is True
    cred = load_cred(path)
    assert cred.public == "pub"
    assert cred.seed == "priv"


def test_write_live_cred_refuses_withdraw_and_blank(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    with pytest.raises(ValueError, match="withdraw"):
        write_live_cred(vault, api_id="ok", seed="withdraw-token")
    with pytest.raises(ValueError, match="id required"):
        write_live_cred(vault, api_id="  ", seed="priv")
    assert cred_present(vault) is False


def test_write_live_cred_refuses_symlink(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    target = tmp_path / "outside.cred"
    target.write_text("id=x\nseed=y\n", encoding="utf-8")
    path = live_cred_path(vault)
    path.symlink_to(target)
    with pytest.raises(VaultError, match="symlink"):
        write_live_cred(vault, api_id="pub", seed="priv")
    assert target.read_text(encoding="utf-8") == "id=x\nseed=y\n"


def test_pack_excludes_live_cred(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    write_live_cred(vault, api_id="pub", seed="priv-seed-not-in-pack")
    backup = tmp_path / "bak"
    manifest = pack(vault, backup)
    blob = str(manifest)
    assert "live.cred" not in blob
    assert "priv-seed-not-in-pack" not in blob
    assert not (backup / "live.cred").exists()
    assert (vault.root / "live.cred").is_file()
