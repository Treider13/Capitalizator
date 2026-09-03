"""Night contour: facts of the day only — report, overlay, calibration, exam, ОКО/intel state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.night import run_night
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def test_night_cli_writes_report(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import open_knowledge as open_k
    from capitalizator.ops.night import main

    vault = init_vault(tmp_path / "desk")
    assert main(["--userdir", str(vault.root), "--day", "2026-08-31"]) == 0
    knowledge = open_k(vault)
    try:
        assert knowledge.report(day="2026-08-31", kind="map")
        assert knowledge.get_overlay("2026-08-31:shadow") is not None
        assert knowledge.meta("exam_night") and knowledge.meta("oko_night")
    finally:
        knowledge.close()


def test_night_records_facts_and_never_promotes(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    assert out["n_shadow"] == 0 and out["r_shadow"] is None
    assert out["exam_passed"] is False and out["classes"] == 0
    assert "card" not in out and "fragility" not in out and "replayed" not in out  # placeholders gone
    exam = json.loads(knowledge.meta("exam_night"))
    assert exam["passed"] is False and exam["challenger"]["n"] == 0
    assert knowledge.meta("champion") is None  # the night never flips the champion
    oko = json.loads(knowledge.meta("oko_night"))
    assert oko["passports"] == {} and oko["mirror"] is None
    intel = json.loads(knowledge.meta("intel_night"))
    assert intel["news_pit"] == []
    assert intel["news_pit_n"] == 0
    assert out["news_pit_n"] == 0
    knowledge.close()


def test_night_news_store_sees_intel_calendar(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_intel_item(
        "rss-hack",
        kind="rss",
        source_id="rss:https://announce.bybit.com",
        known_at=NOW.isoformat(),
        payload={"text": "Hot wallet hack", "event_class": "HACK", "url": "https://announce.bybit.com"},
    )
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    intel = json.loads(knowledge.meta("intel_night"))
    assert out["news_pit_n"] == 1
    assert intel["news_pit_n"] == 1
    assert intel["news_pit"] == [{"class": "HACK", "n": 1}]
    knowledge.close()


def test_night_scores_journal_shadow_r(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_journal_touch(
        "t1",
        {
            "touch_ts": "2026-08-31T14:10:00+00:00",
            "shadow_would": True,
            "shadow_tag": "bounce",
            "outcome": "bounce",
        },
    )
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    assert out["n_shadow"] == 1
    assert out["r_shadow"] == "1"
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    knowledge.close()


def test_day_map_counts_every_touch_of_the_day_resolved_or_not(tmp_path: Path) -> None:
    """The map used to be built from `load_pending` (pending rows with a still-stored
    zone only): resolved touches and touches on retired zones vanished from the day."""
    from capitalizator.ops.night import day_rows

    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    base = {
        "symbol": "BTCUSDT", "zone_id": "z-gone", "zone_lo": "100", "zone_hi": "100.2",
        "zone_side": "support", "zone_tf": "15m", "zone_method": "swing",
        "trade_px": "100.1", "trade_qty": "1",
    }
    knowledge.put_journal_touch("t-bounce", {**base, "touch_ts": "2026-08-31T10:00:00+00:00",
                                             "outcome": "bounce", "zlg_label": "DEFEND",
                                             "tape_eaten": False})
    knowledge.put_journal_touch("t-break", {**base, "touch_ts": "2026-08-31T12:00:00+00:00",
                                            "outcome": "break", "zlg_label": "RETREAT",
                                            "tape_eaten": True, "skip_reason": "SPLIT"})
    knowledge.put_journal_touch("t-pending", {**base, "touch_ts": "2026-08-31T14:00:00+00:00",
                                              "outcome": "pending"})
    knowledge.put_journal_touch("t-other-day", {**base, "touch_ts": "2026-08-30T14:00:00+00:00",
                                                "outcome": "bounce"})
    # an old row without zone facts and without a stored zone cannot be placed on the map
    knowledge.put_journal_touch("t-no-zone", {"symbol": "ETHUSDT", "zone_id": "z-unknown",
                                              "touch_ts": "2026-08-31T15:00:00+00:00",
                                              "trade_px": "4000", "trade_qty": "1",
                                              "outcome": "die"})
    rows, unplaced = day_rows(knowledge, "2026-08-31")
    assert sorted(t.touch_id for _, t in rows) == ["t-bounce", "t-break", "t-pending"]
    assert unplaced == ["t-no-zone"]
    zone = rows[0][0]
    assert (str(zone.lo), str(zone.hi), zone.side, zone.tf) == ("100", "100.2", "support", "15m")
    touch = {t.touch_id: t for _, t in rows}
    assert touch["t-break"].outcome == "break" and touch["t-break"].tape_eaten is True
    assert touch["t-break"].gesture == "RETREAT"
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    assert out["n_rows"] == 3 and out["n_rows_unplaced"] == 1
    assert "3 касания" in out["report"] and "eaten 1" in out["report"]
    knowledge.close()
