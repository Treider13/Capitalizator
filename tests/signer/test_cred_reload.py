"""Signer reloads `{userdir}/live.cred` on each send so Chronos can write it."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, set_user_mode
from capitalizator.ops.user_keys import write_live_cred
from capitalizator.ops.vault import init_vault
from capitalizator.signer import __main__ as signer_main
from capitalizator.signer.cred import Cred, default_cred_file


def test_default_cred_file_is_userdir_live_cred(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    assert default_cred_file(vault.root) == vault.root / "live.cred"


def test_build_send_reloads_file_written_after_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    mark_hello(vault, ok=True)
    set_user_mode(vault, "live", ack=True)
    path = default_cred_file(vault.root)
    send = signer_main.build_send(path, vault=vault)
    seen: list[Cred] = []

    def fake_submit(cred: Cred, row: dict, *, host: str) -> dict:
        seen.append(cred)
        return {"status": "sent", "symbol": row["symbol"], "host": host}

    monkeypatch.setattr(signer_main, "submit_limit", fake_submit)
    row = {"symbol": "BTCUSDT", "trading_mode": "mainnet"}
    with pytest.raises(ValueError, match="cred file"):
        send(row)
    write_live_cred(vault, api_id="after", seed="later")
    out = send(row)
    assert out["status"] == "sent"
    assert seen[0].public == "after"
    assert seen[0].seed == "later"


def test_build_send_demo_stays_not_sent(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    write_live_cred(vault, api_id="pub", seed="priv")
    send = signer_main.build_send(default_cred_file(vault.root), vault=vault)
    out = send({"symbol": "BTCUSDT", "trading_mode": "testnet"})
    assert out == {"status": "not_sent", "reason": "not_live"}
