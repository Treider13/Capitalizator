"""Harvest / A+ / pyramid are facts for the existing Alerter. Not a new bot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.alerts import KINDS, event_text, stamp
from capitalizator.ops.alerts import Alerter
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.schema import Intent
from capitalizator.signer.process import _alert_transitions

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def test_event_texts_have_no_advice() -> None:
    assert set(KINDS) == {"harvest", "aplus", "pyramid"}
    for kind in KINDS:
        text = event_text(kind=kind, symbol="BTCUSDT")
        assert text
        assert not contains_advice(text)
        assert not contains_advice(json.dumps({"kind": kind, "symbol": "BTCUSDT"}))


def test_stamp_writes_hyexec_event(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    row = stamp(kn, kind="pyramid", symbol="BTCUSDT", at=NOW)
    assert row["kind"] == "pyramid"
    raw = kn.meta("hyexec_event")
    assert raw is not None
    assert json.loads(raw)["kind"] == "pyramid"
    kn.close()


def test_signer_alerts_on_hyexec_event_change(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    sent: list[bytes] = []
    al = Alerter("t", "c", post=lambda _u, b: (sent.append(b), 200)[1])
    stamp(kn, kind="harvest", symbol="BTCUSDT", at=NOW)
    _alert_transitions(al, kn, blocked=[], mode="demo", when=NOW)
    assert sent
    last = kn.meta("alerts_last")
    assert last is not None and "hyexec_event" in last
    n = len(sent)
    _alert_transitions(al, kn, blocked=[], mode="demo", when=NOW)
    assert len(sent) == n
    kn.close()


def test_add_in_profit_stamps_pyramid(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
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
    desk.tick(NOW)
    raw = desk.knowledge.meta("hyexec_event")
    assert raw is not None
    assert json.loads(raw)["kind"] == "pyramid"
