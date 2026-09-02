"""Knowledge bus: WAL, BEGIN IMMEDIATE, broken JSON is None."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.card.live import CardLive
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)


def _card() -> CardLive:
    return CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="OTE",
        fvg_status="filled",
        sweep_status="done",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
    )


def test_writable_desk_sqlite_is_wal(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "desk"))
    kn.put_card_live("BTCUSDT", _card().to_payload())
    mode = kn._cx.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    kn.close()


def test_get_spot_ack_broken_json_returns_none(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "desk"))
    kn._cx.execute("BEGIN IMMEDIATE")
    kn._cx.execute(
        "INSERT OR REPLACE INTO claim(id, payload) VALUES (?, ?)",
        ("spot_ack:BADUSDT", "{broken"),
    )
    kn._cx.commit()
    assert kn.get_spot_ack("BADUSDT") is None
    kn.close()
