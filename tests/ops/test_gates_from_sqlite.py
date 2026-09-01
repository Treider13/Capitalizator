from pathlib import Path

from capitalizator.ops.gates_from_sqlite import gates_from_sqlite
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_empty_journal_keeps_gates_red(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    try:
        out = gates_from_sqlite(knowledge)
    finally:
        knowledge.close()
    assert out["n_touches"] == 0
    assert out["n_shadow"] == 0
    assert out["n_episodes"] == 0
    assert out["phases"]["f0"]["ok"] is False
    assert out["phases"]["f1"]["ok"] is False
    assert out["phases"]["f5"]["ok"] is False
