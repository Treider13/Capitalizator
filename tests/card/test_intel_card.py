"""Э5: live intel (RSS announcements, whale text) moves Card B veto/cut/hold."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.card.build import from_news
from capitalizator.card.live import VolumeSnapshot
from capitalizator.desk.loop import DeskLoop
from capitalizator.news_macro.from_intel import (
    calendar_from_intel,
    claims_from_intel,
    row_from_item,
)
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.whales.no_single import sole_whale

NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def test_rss_hack_item_becomes_newsrow() -> None:
    row = row_from_item(
        {
            "id": "rss-hack",
            "kind": "rss",
            "source_id": "rss:https://announce.bybit.com",
            "known_at": NOW.isoformat(),
            "text": "Exchange hack drains hot wallet",
            "event_class": "HACK",
        }
    )
    assert row is not None
    assert row.event_class == "HACK"
    assert row.announce_tz == "UTC"
    assert row.size_rule == "intel"


def test_other_headline_without_negative_is_dropped() -> None:
    assert (
        row_from_item(
            {
                "id": "rss-meh",
                "kind": "rss",
                "known_at": NOW.isoformat(),
                "text": "Market wrap: volumes steady",
                "event_class": "OTHER",
            }
        )
        is None
    )


def test_intel_hack_vetoes_card() -> None:
    row = row_from_item(
        {
            "id": "rss-hack",
            "kind": "rss",
            "known_at": NOW.isoformat(),
            "text": "Protocol hack",
            "event_class": "HACK",
        }
    )
    assert row is not None
    card = from_news(
        symbol="BTCUSDT",
        now=NOW,
        calendar=(row,),
        volume=VolumeSnapshot(rvol="3"),
    )
    assert card.bearing_verdict == "veto"
    assert "coin_negative" in card.minuses


def test_intel_cpi_inside_2h_vetoes() -> None:
    row = row_from_item(
        {
            "id": "rss-cpi",
            "kind": "rss",
            "known_at": NOW.isoformat(),
            "event_time": (NOW + timedelta(hours=1)).isoformat(),
            "text": "US CPI due in one hour",
            "event_class": "CPI",
        }
    )
    assert row is not None
    card = from_news(symbol="ETHUSDT", now=NOW, calendar=(row,), volume=VolumeSnapshot(rvol="1"))
    assert card.bearing_verdict == "veto"
    assert "fomc_inside_2h" in card.minuses


def test_intel_fomc_tomorrow_cuts_size() -> None:
    row = row_from_item(
        {
            "id": "rss-fomc",
            "kind": "rss",
            "known_at": NOW.isoformat(),
            "event_time": (NOW + timedelta(hours=10)).isoformat(),
            "text": "FOMC statement tomorrow",
            "event_class": "FOMC",
        }
    )
    assert row is not None
    card = from_news(symbol="BTCUSDT", now=NOW, calendar=(row,), volume=VolumeSnapshot(rvol="3"))
    assert card.bearing_verdict == "cut_size"
    assert card.macro_multiplier == Decimal("0.5")


def test_calendar_from_intel_reads_sqlite(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_intel_item(
        "rss-hack",
        kind="rss",
        source_id="rss:https://announce.bybit.com",
        known_at=NOW.isoformat(),
        payload={"text": "Hot wallet hack", "event_class": "HACK", "url": "https://announce.bybit.com"},
    )
    cal = calendar_from_intel(kn, now=NOW)
    kn.close()
    assert len(cal) == 1
    assert cal[0].event_class == "HACK"


def test_publish_card_uses_intel_announcement(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_intel_item(
        "rss-hack",
        kind="rss",
        source_id="rss:https://announce.bybit.com",
        known_at=NOW.isoformat(),
        payload={"text": "Hot wallet hack", "event_class": "HACK", "url": "https://announce.bybit.com"},
    )
    desk = DeskLoop(knowledge=kn, user_mode="off")
    card = desk.publish_card("BTCUSDT", NOW)
    assert card.bearing_verdict == "veto"
    stored = kn.get_card_live("BTCUSDT")
    assert stored is not None
    assert stored["bearing_verdict"] == "veto"


def test_sole_whale_intel_holds_card(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_intel_item(
        "x-whale",
        kind="x_account",
        source_id="x:example",
        known_at=NOW.isoformat(),
        payload={"text": "whale wallet 0xabc bought the dip", "url": "https://x.com/example"},
    )
    items = kn.intel_items(kind="x_account")
    assert sole_whale(claims_from_intel(items))
    desk = DeskLoop(knowledge=kn, user_mode="off")
    card = desk.publish_card("BTCUSDT", NOW)
    assert card.bearing_verdict == "hold"
    assert "whale_only" in card.minuses


def test_publish_card_rss_cpi_without_csv_does_not_veto(tmp_path: Path) -> None:
    """Intel CPI chatter is a headline, not an 08:30 ET clock."""
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_intel_item(
        "rss-cpi",
        kind="rss",
        source_id="rss:https://example.com/feed",
        known_at=NOW.isoformat(),
        payload={
            "text": "US CPI due in one hour",
            "event_class": "CPI",
            "event_time": (NOW + timedelta(hours=1)).isoformat(),
            "url": "https://example.com/cpi",
        },
    )
    desk = DeskLoop(knowledge=kn, user_mode="off", calendar=())
    card = desk.publish_card("BTCUSDT", NOW)
    kn.close()
    assert "fomc_inside_2h" not in card.minuses


def test_from_news_nfp_csv_inside_2h_vetoes() -> None:
    row = row_from_item(
        {
            "id": "nfp-csv",
            "kind": "rss",
            "known_at": NOW.isoformat(),
            "event_time": (NOW + timedelta(hours=1)).isoformat(),
            "text": "NFP",
            "event_class": "NFP",
        }
    )
    assert row is not None
    card = from_news(
        symbol="BTCUSDT",
        now=NOW,
        calendar=(row,),
        volume=VolumeSnapshot(rvol="3"),
    )
    assert card.bearing_verdict == "veto"
    assert "fomc_inside_2h" in card.minuses


def test_author_weights_fill_jury_b(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.set_meta(
        "author_weights",
        json.dumps(
            {
                "at": NOW.isoformat(),
                "authors": {"a1": {"hits": 3, "n": 8, "weight": "0.1"}},
            }
        ),
    )
    desk = DeskLoop(knowledge=kn, user_mode="off")
    card = desk.publish_card("BTCUSDT", NOW)
    assert card.jury_b_n == 8
    assert card.jury_b_for == 3
