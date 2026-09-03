"""D-32…D-37: the console shows money, positions, queue statuses and honest banners;
operator risk menu and commands reach the desk."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.account_view import account_view, paper_stats, queue_view
from capitalizator.ops.console import ConsoleApp, _api_get, desk_snapshot, render_html
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.config import load_risk_config

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def test_banners_say_what_is_missing_not_zero(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    view = account_view(kn, now=NOW)
    text = " ".join(view["banners"])
    assert "ДЕСК: нет сердцебиения" in text
    assert "РЕКОРДЕР: статуса нет" in text
    assert "БИРЖА: состояния нет" in text
    assert "КОМИССИЯ — предположение" in text
    assert view["account"] is None and view["paper"]["all"]["n"] == 0
    # a desk tick writes heartbeat + account snapshot → those banners change
    desk = DeskLoop(knowledge=kn, user_mode="off")
    desk.tick(NOW)
    view = account_view(kn, now=NOW + timedelta(seconds=2))
    text = " ".join(view["banners"])
    assert "ДЕСК молчит" not in text and "нет сердцебиения" not in text
    assert "ЭКВИТИ бумажное" in text
    view = account_view(kn, now=NOW + timedelta(seconds=30))
    assert any(b.startswith("ДЕСК молчит") for b in view["banners"])
    kn.set_meta("exchange_state", json.dumps({
        "at": NOW.isoformat(), "equity": "99000", "positions": [], "mismatches": [{"symbol": "ETHUSDT"}],
        "stop_missing": ["BTCUSDT"],
    }))
    kn.set_meta("entries_blocked", json.dumps(["reconcile_mismatch"]))
    view = account_view(kn, now=NOW + timedelta(seconds=3))
    text = " ".join(view["banners"])
    assert "СВЕРКА: 1 расхождений" in text and "СТОП НЕ ПОДТВЕРЖДЁН биржей: BTCUSDT" in text
    assert "ВХОДЫ ЗАБЛОКИРОВАНЫ: reconcile_mismatch" in text
    kn.close()


def test_paper_stats_exclude_unfilled_and_report_ci() -> None:
    rows = [
        {"entry_px": "100", "r_net": "1.5", "realized": "3", "fees": "0.1", "funding": "0", "exit_reason": "tp", "mae_r": "0.2"},
        {"entry_px": "100", "r_net": "-1.1", "realized": "-2", "fees": "0.2", "funding": "0", "exit_reason": "stop", "mae_r": "1.1"},
        {"entry_px": None, "r_net": None, "exit_reason": "expired"},
    ]
    st = paper_stats(rows)
    assert st["n"] == 2 and st["n_unfilled"] == 1
    assert st["winrate"] == "0.5" and st["winrate_ci95"] is not None
    lo, hi = (Decimal(x) for x in st["winrate_ci95"])
    assert lo < Decimal("0.5") < hi and hi - lo > Decimal("0.5")  # n=2 → very wide
    assert Decimal(st["profit_factor"]) > 1 and st["exit_reasons"] == {"tp": 1, "stop": 1}
    assert st["pnl_net"] == "0.7" and st["mae_r_p90"] == "1.1"


def test_api_endpoints_and_html_contain_money(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    kn.enqueue_intent({"symbol": "BTCUSDT", "side": "buy", "entry": "1", "stop": "0.9", "tp": "1.2",
                       "tag": "bounce", "qty": "1"}, created_ts=NOW.isoformat())
    kn.mark_intent(1, "failed")
    kn.enqueue_oms(kind="flatten", symbol="BTCUSDT", payload={"reason": "test"}, created_ts=NOW.isoformat())
    kn.close()
    acct = _api_get(vault, "/api/account", {})
    assert acct is not None and "banners" in acct and "risk_config" in acct
    q = _api_get(vault, "/api/queue", {})
    assert q["counts"] == {"failed": 1} and q["oms"][0]["kind"] == "flatten"
    assert _api_get(vault, "/api/paper", {})["trades"] == []
    assert _api_get(vault, "/api/risk", {})["risk_config"]["target_risk_pct"] == "0.01"
    snap = desk_snapshot(vault)
    assert snap["queue_counts"] == {"failed": 1}
    page = render_html(vault)
    assert "Счёт" in page and "Предупреждения" in page and "позиций нет" in page
    assert "БИРЖА: состояния нет" in page


def test_risk_menu_and_commands_reach_the_desk(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    app = ConsoleApp(vault)
    try:
        app.set_risk({"target_risk_pct": "0.02"}, ack=False)
    except ValueError as exc:
        assert "ack" in str(exc)
    try:
        app.set_risk({"nonsense": "1"}, ack=True)
    except ValueError as exc:
        assert "unknown risk keys" in str(exc)
    try:
        app.set_risk({"target_risk_pct": "0.5"}, ack=True)
    except ValueError:
        pass  # RiskConfig validation refuses 50% risk
    out = app.set_risk({"target_risk_pct": "0.02", "max_open_positions": 2, "allow_night": "true"}, ack=True)
    assert out["risk_config"]["target_risk_pct"] == "0.02" and out["risk_config"]["version"] == 2
    kn = open_knowledge(vault)
    desk = DeskLoop(knowledge=kn, user_mode="off")
    assert desk.risk_config.target_risk_pct == Decimal("0.02") and desk.risk.max_open == 2
    # a later change is picked up on the next tick (hot reload, new intents only)
    app.set_risk({"max_open_positions": 3}, ack=True)
    desk.tick(NOW)
    assert desk.risk.max_open == 3 and desk.risk_config.config_id == load_risk_config(kn).config_id
    # commands: pause / resume / release halts / flatten ALL
    app.command("pause_entries", symbol=None, ack=True)
    events = desk.tick(NOW + timedelta(seconds=1))
    assert {"event": "pause_entries"} in events and desk.entries_paused
    desk.account.halts.halted, desk.account.halts.reason = True, "peak"
    app.command("release_halts", symbol=None, ack=True)
    app.command("resume_entries", symbol=None, ack=True)
    app.command("flatten", symbol="ALL", ack=True)
    events = desk.tick(NOW + timedelta(seconds=2))
    kinds = [e["event"] for e in events]
    assert "release_halts" in kinds and "resume_entries" in kinds
    assert not desk.account.halts.halted and not desk.entries_paused
    # transactional queue: every command claimed and marked, none left pending
    cmds = kn.commands()
    assert cmds and all(c["status"] == "done" for c in cmds)
    assert {c["kind"] for c in cmds} >= {"pause_entries", "release_halts", "resume_entries", "flatten"}
    assert kn.claim_commands() == []
    try:
        app.command("flatten", symbol=None, ack=True)
    except ValueError as exc:
        assert "symbol" in str(exc)
    kn.close()


def test_queue_view_without_db_is_empty(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault, create=False)
    assert queue_view(kn) == {"intents": [], "orders": [], "oms": [], "counts": {}}
