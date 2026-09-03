"""Console read-models for the sessions release: /api/sessions, /api/universe, /api/preview,
and POST /api/universe apply with ack."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.ops.account_view import preview_view, sessions_view, universe_view
from capitalizator.ops.console import ConsoleApp, _api_get
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.screener.refresh import META_PROPOSAL

MONDAY_OVERLAP = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_sessions_view_reports_policy_now_and_paper_by_window(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    kn.put_paper_trade({"paper_id": "a:shadow", "touch_id": "a", "source": "shadow", "symbol": "BTCUSDT",
                        "closed_at": MONDAY_OVERLAP.isoformat(), "tag": "bounce", "entry_px": "100",
                        "r_net": "1.2", "realized": "1", "fees": "0.1", "funding": "0",
                        "labels": {"window": "asia"}})
    kn.put_paper_trade({"paper_id": "b:shadow", "touch_id": "b", "source": "shadow", "symbol": "BTCUSDT",
                        "closed_at": MONDAY_OVERLAP.isoformat(), "tag": "bounce", "entry_px": "100",
                        "r_net": "-1", "realized": "-1", "fees": "0.1", "funding": "0",
                        "labels": {}})
    kn.set_meta("budget:2026-08-31:overlap", "3")
    view = sessions_view(kn, now=MONDAY_OVERLAP)
    assert view["now"]["window"] == "overlap" and view["now"]["budget_key"] == "2026-08-31:overlap"
    assert view["now"]["size_mult"] == "1.0" and view["now"]["blackouts"] == []
    names = [w["name"] for w in view["windows"]]
    assert names == ["asia", "europe", "overlap", "us", "night", "weekend"]
    night = next(w for w in view["windows"] if w["name"] == "night")
    assert night["closed"] is True and night["end"] == "24:00"
    assert view["budget_spent_today"] == {"overlap": 3}
    assert view["paper_by_window"]["shadow"]["asia"]["n"] == 1
    assert view["paper_by_window"]["shadow"]["unlabelled"]["n"] == 1
    assert view["funding_blackout_min"] == 5 and view["us_data_day_block_windows"] == ["asia"]
    kn.close()


def test_universe_view_and_apply_through_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    view = universe_view(kn)
    assert "BTCUSDT" in view["current"] and view["proposal"] is None
    # a proposal stored by the signer; apply writes the vault's universe.yaml (the image
    # is read-only and every process mounts the data dir — CAP_USERDIR points there)
    from capitalizator.screener.universe import default_desk_path, load_desk_universe

    monkeypatch.setenv("CAP_USERDIR", str(vault.root))
    monkeypatch.delenv("CAP_UNIVERSE", raising=False)
    target = vault.root / "universe.yaml"
    kn.set_meta(META_PROPOSAL, json.dumps({"proposal_id": "abc", "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}))
    kn.close()
    app = ConsoleApp(vault)
    with pytest.raises(ValueError, match="ack"):
        app.apply_universe("abc", ack=False)
    with pytest.raises(ValueError, match="proposal_id"):
        app.apply_universe("zzz", ack=True)
    out = app.apply_universe("abc", ack=True)
    assert out["universe"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert "SOLUSDT" in target.read_text()
    # every reader now resolves to the applied file; week0 still wins when asked for
    assert default_desk_path() == target and "SOLUSDT" in load_desk_universe().symbols
    monkeypatch.setenv("CAP_UNIVERSE", "week0")
    assert list(load_desk_universe().symbols) == ["BTCUSDT", "ETHUSDT"]
    monkeypatch.delenv("CAP_UNIVERSE")
    got = _api_get(vault, "/api/universe", {})
    assert got["applied"]["proposal_id"] == "abc"


def test_preview_view_reads_the_journal_row(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    assert preview_view(kn, touch_id="nope")["found"] is False
    iid = kn.enqueue_intent({"symbol": "BTCUSDT", "side": "buy", "entry": "100", "stop": "99",
                             "tp": "102", "tag": "bounce", "qty": "1",
                             "stop_components": {"structural": "99.2", "k_atr": "0.5"}},
                            created_ts=MONDAY_OVERLAP.isoformat())
    kn.put_journal_touch("t1", {"touch_id": "t1", "symbol": "BTCUSDT", "idea": "bounce",
                                "idea_side": "buy", "jury": "ACCORD", "touch_ts": MONDAY_OVERLAP.isoformat(),
                                "session_window": "overlap", "session_gate": "window:overlap",
                                "session_size_mult": "1.0", "session_k_atr": "0.5",
                                "intent_id": iid, "sizing": {"qty": "1"}, "ev": {"ok": True},
                                "size_mult_applied": "1"})
    view = preview_view(kn, touch_id=None)  # latest ACCORD
    assert view["found"] and view["touch_id"] == "t1" and view["sent"] is True
    assert view["session"]["window"] == "overlap"
    assert view["stop_components"]["k_atr"] == "0.5" and view["intent"]["stop"] == "99"
    kn.close()
    assert _api_get(vault, "/api/preview", {"touch_id": ["t1"]})["found"] is True
    assert _api_get(vault, "/api/sessions", {})["now"]["window"] in {
        "asia", "europe", "overlap", "us", "night", "weekend"
    }
