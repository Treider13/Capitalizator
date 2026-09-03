"""Demo → live keeps the same book. r_demo is prior, not a live fill."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.card.live import CardLive
from capitalizator.ops.handoff import experience_snapshot, prior_r
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, read_user_mode, set_user_mode
from capitalizator.ops.settings import Settings
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


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


def _keys(vault, *, mode: str = "demo") -> None:
    Settings(vault).update(
        {
            "bybit.api_key": "testkey12",
            "bybit.api_secret": "testsecret",
            "bybit.mode": mode,
        },
        ack=True,
    )


def test_demo_to_live_keeps_journal_card_and_overlay(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    _keys(vault)
    kn = open_knowledge(vault)
    kn.put_card_live("BTCUSDT", _card().to_payload())
    kn.put_journal_touch(
        "t-demo",
        {"symbol": "BTCUSDT", "jury": "ACCORD", "cav_label": "REJECT", "zlg_label": "DEFEND"},
    )
    kn.put_overlay("bounce", r_shadow="0.2", r_demo="0.8", r_live=None)
    kn.append_episode(
        {
            "trade_id": "e-demo",
            "mode": "demo",
            "zone_id": "z1",
            "gesture": "DEFEND",
            "fill": NOW,
            "slip": "0",
            "fees": "0",
            "r": "0.8",
        }
    )
    kn.close()
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    out = set_user_mode(vault, "live", ack=True, override_reason="owner after F4 review")
    assert out["user_mode"] == "live"
    assert out["from_mode"] == "demo"
    assert out["experience"]["handoff_from"] == "demo"
    assert out["experience"]["n_touches"] == 1
    assert out["experience"]["n_episodes_demo"] == 1
    assert out["experience"]["n_cards"] == 1
    assert read_user_mode(vault) == "live"
    kn = open_knowledge(vault)
    assert kn.get_card_live("BTCUSDT") is not None
    assert len(kn.journal_rows()) == 1
    row = kn.get_overlay("bounce")
    assert row is not None
    assert row["r_demo"] == "0.8"
    assert row["r_live"] is None
    assert prior_r(row) == {"r": "0.8", "source": "r_demo"}
    assert experience_snapshot(kn)["same_book"] is True
    kn.close()


def test_off_to_live_does_not_invent_handoff(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    _keys(vault, mode="live_sub")
    mark_hello(vault, ok=True)
    set_user_mode(vault, "live", ack=True, override_reason="owner after F4 review")
    kn = open_knowledge(vault)
    snap = experience_snapshot(kn)
    assert snap["handoff_from"] is None
    assert snap["n_touches"] == 0
    kn.close()


def test_prior_r_prefers_live_then_demo() -> None:
    assert prior_r({"r_live": "1.1", "r_demo": "0.4"}) == {"r": "1.1", "source": "r_live"}
    assert prior_r({"r_live": None, "r_demo": None, "r_shadow": "0.2"}) == {
        "r": "0.2",
        "source": "r_shadow",
    }
    assert prior_r({}) == {"r": None, "source": "none"}
