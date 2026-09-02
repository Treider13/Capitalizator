"""Old overlay table gains r_challenger without wiping measured R."""

from __future__ import annotations

import sqlite3

from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.vault import init_vault


def test_old_overlay_column_is_added(tmp_path) -> None:
    vault = init_vault(tmp_path / "old")
    open_knowledge(vault).close()
    cx = sqlite3.connect(vault.db_path)
    cx.execute("DROP TABLE overlay")
    cx.execute(
        "CREATE TABLE overlay ("
        "setup_id TEXT PRIMARY KEY, r_shadow TEXT, r_demo TEXT, r_live TEXT)"
    )
    cx.execute(
        "INSERT INTO overlay(setup_id, r_shadow, r_demo, r_live) "
        "VALUES ('2026-08-31:shadow', NULL, '1.5', NULL)"
    )
    cx.commit()
    cx.close()
    knowledge = Knowledge(vault.db_path, create=True)
    try:
        persist = knowledge.get_overlay("2026-08-31:shadow")
        assert persist is not None
        assert persist["r_demo"] == "1.5"
        assert persist["r_challenger"] is None
        knowledge.put_overlay("2026-08-31:shadow", r_demo="1.5", r_challenger="1")
        row = knowledge.get_overlay("2026-08-31:shadow")
        assert row is not None
        assert row["r_challenger"] == "1"
        assert row["r_demo"] == "1.5"
    finally:
        knowledge.close()
