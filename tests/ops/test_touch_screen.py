"""P7 — full touch page shows B + A marks. No advice. No orders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from capitalizator.card.live import CardLive, VolumeSnapshot
from capitalizator.ops.console import desk_snapshot
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.touch_screen import render_html as render_touch
from capitalizator.ops.touch_screen import touch_screen
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)


def _card(
    *,
    sweep_long: str = "none",
    sweep_short: str = "none",
    sweep_status: str = "done",
) -> CardLive:
    return CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="OTE",
        fib_level="0.718",
        rsi_htf="52",
        gex_bg="+2.1M",
        fvg_status="filled",
        sweep_status=sweep_status,  # type: ignore[arg-type]
        sweep_long=sweep_long,  # type: ignore[arg-type]
        sweep_short=sweep_short,  # type: ignore[arg-type]
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
        volume=VolumeSnapshot(rvol="2.3", poc="100", vah="101", val="99"),
    )


def test_p7_screen_has_b_and_a() -> None:
    screen = touch_screen(
        symbol="BTCUSDT",
        card=_card(),
        jury="ACCORD",
        cav="REJECT",
        zlg="DEFEND",
        tape_eaten=False,
        btc="box",
        n_cav=20,
        n_zlg=20,
    )
    assert screen["line"].startswith("[TOUCH] BTCUSDT | B:propose | A:ACCORD")
    assert screen["b"]["fib"] == "0.718(OTE)"
    assert screen["b"]["rvol"] == "2.3"
    assert screen["a"]["cav"] == "REJECT"
    assert screen["a"]["zlg"] == "DEFEND"
    assert "--- B ---" in screen["text"]
    assert "--- A ---" in screen["text"]
    page = render_touch(screen)
    assert "0.718(OTE)" in page
    assert "REJECT" in page
    assert "ордеров нет" in page.lower()
    for word in ("лонг", "шорт", "купи", "продай", "завтра"):
        assert word not in page.lower()
        assert word not in screen["text"].lower()


def test_p7_empty_screen_is_honest() -> None:
    page = render_touch(None)
    assert "касаний нет" in page


def test_p7_missing_card_says_no_card() -> None:
    screen = touch_screen(symbol="ETHUSDT", card=None, jury=None)
    assert screen["b"]["verdict"] == "no card"
    assert "B:no card" in screen["line"]
    assert "B:hold" not in screen["line"]


def test_p7_stale_card_says_stale() -> None:
    stale = _card()
    later = NOW + timedelta(seconds=61)
    screen = touch_screen(symbol="BTCUSDT", card=stale, jury="ACCORD", now=later)
    assert screen["b"]["verdict"] == "stale"
    assert "B:stale" in screen["line"]


def test_p7_console_snapshot_includes_touch(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    card = _card()
    kn.put_card_live("BTCUSDT", card.to_payload())
    kn.put_journal_touch(
        "t1",
        {
            "symbol": "BTCUSDT",
            "jury": "ACCORD",
            "cav_label": "REJECT",
            "zlg_label": "DEFEND",
            "tape_eaten": False,
            "btc_state": "box",
            "n_cav": 20,
            "n_zlg": 20,
        },
    )
    kn.close()
    snap = desk_snapshot(vault)
    assert snap["touch"] is not None
    assert snap["touch"]["a"]["jury"] == "ACCORD"
    html = render_touch(snap["touch"])
    assert "[TOUCH] BTCUSDT" in html
    assert "<h3>B</h3>" in html
    assert "<h3>A</h3>" in html
    assert "--- B ---" in snap["touch"]["text"]


def test_p7_module_has_no_signer() -> None:
    import capitalizator.ops.touch_screen as pkg

    assert "signer" not in pkg.__dict__


def test_p7_sweep_follows_idea_side() -> None:
    long_card = _card(sweep_long="done", sweep_short="pending")
    long_screen = touch_screen(
        symbol="BTCUSDT",
        card=long_card,
        jury="ACCORD",
        idea_side="buy",
    )
    assert long_screen["b"]["sweep_for"] == "done"
    assert long_screen["b"]["sweep_long"] == "done"
    assert "sweep_for:done" in long_screen["text"]
    short_screen = touch_screen(
        symbol="BTCUSDT",
        card=_card(sweep_long="pending", sweep_short="done"),
        jury="ACCORD",
        idea_side="sell",
    )
    assert short_screen["b"]["sweep_for"] == "done"
    assert short_screen["b"]["sweep_short"] == "done"
    page = render_touch(short_screen)
    for word in ("лонг", "шорт", "купи", "продай"):
        assert word not in page.lower()


def test_p7_footprint_is_opinion_not_advice() -> None:
    screen = touch_screen(
        symbol="BTCUSDT",
        card=_card(),
        jury="ACCORD",
        cav="REJECT",
        zlg="DEFEND",
        tape_eaten=False,
        oko_label="CLEAN",
        oko_footprint="ICEBERG",
        oko_footprint_side="bid",
        oko_regime="RANGE",
    )
    assert screen["a"]["oko_footprint"] == "ICEBERG"
    assert screen["a"]["oko_footprint_side"] == "bid"
    assert screen["b"]["sweep_long"] in {"none", "done", "pending"}
    assert screen["b"]["sweep_short"] in {"none", "done", "pending"}
    assert "tape_eaten" in screen["text"]
    page = render_touch(screen)
    assert "ICEBERG" in page
    assert "sweep_long" in page
    for word in ("лонг", "шорт", "купи", "продай"):
        assert word not in page.lower()
        assert word not in screen["text"].lower()


def test_no_iceberg_opens_helper() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator"
    bounce = (src / "exec" / "strategy_bounce.py").read_text(encoding="utf-8")
    eyelid = (src / "oko" / "eyelid.py").read_text(encoding="utf-8")
    assert "iceberg_opens" not in bounce
    assert "def oko_opens_size" in eyelid
    from capitalizator.oko.eyelid import oko_opens_size

    assert oko_opens_size() is False
