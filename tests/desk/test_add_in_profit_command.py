"""Desk may journal add_in_profit. It does not invent a venue add. average_in dies."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.schema import Intent, reject_forbidden_keys

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "desk")), user_mode="off")


def _open_long(desk: DeskLoop) -> None:
    desk.account.on_open(
        Intent(
            symbol="BTCUSDT",
            side="buy",
            entry=Decimal("100"),
            stop=Decimal("98"),
            tp=Decimal("104"),
            tag="bounce",
            qty=Decimal("1"),
        ),
        now=NOW,
    )


def test_average_in_is_still_not_a_command() -> None:
    assert "average_in" not in Knowledge.COMMAND_KINDS
    with pytest.raises(ValueError, match="forbidden"):
        reject_forbidden_keys({"action": "average_in"})


def test_add_in_profit_is_a_desk_command() -> None:
    assert "add_in_profit" in Knowledge.COMMAND_KINDS
    assert "add_in_profit" in DeskLoop.DESK_COMMANDS


def test_add_below_long_entry_fails(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _open_long(desk)
    desk.knowledge.enqueue_command(
        "add_in_profit",
        {
            "kind": "add_in_profit",
            "symbol": "BTCUSDT",
            "add_price": "99",
            "extra_risk": "0.005",
        },
        created_ts=NOW.isoformat(),
    )
    desk.tick(NOW)
    row = desk.knowledge.commands()[0]
    assert row["status"] == "failed"
    assert "above entry" in str(row["result"])
    assert not any(c["kind"] == "add" for c in desk.knowledge.oms_rows())


def test_add_in_profit_journals_and_does_not_send(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _open_long(desk)
    start = desk.account.equity
    desk.account.set_equity(start * Decimal("1.075"), source=desk.account.equity_source, now=NOW)
    desk.knowledge.enqueue_command(
        "add_in_profit",
        {
            "kind": "add_in_profit",
            "symbol": "BTCUSDT",
            "add_price": "101.5",
            "extra_risk": "0.005",
        },
        created_ts=NOW.isoformat(),
    )
    out = desk.tick(NOW)
    row = desk.knowledge.commands()[0]
    assert row["status"] == "done"
    assert row["result"]["action"] == "add_in_profit"
    assert row["result"]["venue"] is False
    assert Decimal(row["result"]["add_price"]) == Decimal("101.5")
    journal = desk.knowledge.get_journal_touch("add_in_profit:BTCUSDT")
    assert journal is not None
    assert journal["add_in_profit"]["action"] == "add_in_profit"
    assert journal["add_in_profit"]["venue"] is False
    assert desk.knowledge.oms_rows() == []
    assert any(ev.get("event") == "add_in_profit" and ev.get("venue") is False for ev in out)


def test_add_in_profit_behind_week_pace_fails(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    _open_long(desk)
    desk.knowledge.enqueue_command(
        "add_in_profit",
        {
            "kind": "add_in_profit",
            "symbol": "BTCUSDT",
            "add_price": "101.5",
            "extra_risk": "0.005",
        },
        created_ts=NOW.isoformat(),
    )
    desk.tick(NOW)
    row = desk.knowledge.commands()[0]
    assert row["status"] == "failed"
    assert "behind week pace" in str(row["result"])
    assert desk.knowledge.oms_rows() == []


def test_add_without_open_idea_fails(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.knowledge.enqueue_command(
        "add_in_profit",
        {"kind": "add_in_profit", "symbol": "BTCUSDT", "add_price": "101"},
        created_ts=NOW.isoformat(),
    )
    desk.tick(NOW)
    assert desk.knowledge.commands()[0]["status"] == "failed"
