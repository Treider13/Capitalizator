"""Gateway sees the file Chronos writes, even if it appeared after process start."""

from __future__ import annotations

from pathlib import Path

from capitalizator.gateway.keys import load_keys
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, set_user_mode
from capitalizator.ops.user_keys import write_live_cred
from capitalizator.ops.vault import init_vault


def test_load_keys_reads_file_written_after_start(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    mark_hello(vault, ok=True)
    set_user_mode(vault, "live", ack=True)
    assert load_keys(vault) is None
    write_live_cred(vault, api_id="after", seed="later", mode="live_sub")
    keys = load_keys(vault)
    assert keys is not None
    assert keys.api_key == "after"
    assert keys.api_secret == "later"
    assert keys.mode == "live_sub"


def test_demo_key_file_is_paper_venue(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    write_live_cred(vault, api_id="pub", seed="priv", mode="demo")
    keys = load_keys(vault)
    assert keys is not None
    assert keys.demo is True
    assert keys.live is False
