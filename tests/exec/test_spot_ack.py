"""P5 — listing is spot_proposal. No order until human ack. No Telegram."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.card.build import from_news
from capitalizator.exec.spot import SpotAdapter, in_perp_universe
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.zones.model import Zone

NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
TICK = Decimal("0.1")
NEW = "NEWCOINUSDT"
ZONE = Zone.create(
    symbol=NEW,
    tf="1d",
    side="support",
    lo=Decimal("1.0"),
    hi=Decimal("1.2"),
    method="prior_day_hl",
    created_as_of=NOW,
)


def _listing() -> NewsRow:
    return NewsRow(
        event_id="list-new",
        event_class="LISTING",
        event_time=NOW,
        known_at=NOW - timedelta(minutes=5),
        assets=(NEW,),
        source="bybit",
        announce_tz="UTC",
        size_rule="spot_proposal",
        notes="listing new token",
        raw="listing",
    )


def test_p5_listing_outside_24_is_spot_proposal_hold() -> None:
    assert in_perp_universe(NEW) is False
    card = from_news(symbol=NEW, now=NOW, calendar=(_listing(),))
    assert card.venue == "spot_proposal"
    assert card.bearing_verdict == "hold"
    assert "no_spot_ack" in card.minuses
    assert "listing_base_rate_low" in card.pluses
    assert 5 <= len(card.pluses) + len(card.minuses) <= 7


def test_p5_listing_of_perp_stays_perp() -> None:
    row = NewsRow(
        event_id="list-btc",
        event_class="LISTING",
        event_time=NOW,
        known_at=NOW - timedelta(minutes=5),
        assets=("BTCUSDT",),
        source="bybit",
        announce_tz="UTC",
        size_rule="perp",
        notes="already listed",
        raw="listing",
    )
    card = from_news(symbol="BTCUSDT", now=NOW, calendar=(row,))
    assert card.venue == "perp"
    assert card.bearing_verdict != "hold"


def test_p5_propose_without_ack_is_none() -> None:
    card = from_news(symbol=NEW, now=NOW, calendar=(_listing(),))
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    snap = BounceSnapshot(
        now=NOW,
        symbol=NEW,
        price=Decimal("1.1"),
        tick=TICK,
        trading_mode="demo",
        zone=ZONE,
        zones=(ZONE,),
        jury="ACCORD",
        cav_label="REJECT",
        zlg_label="DEFEND",
        n_cav=20,
        n_zlg=20,
        gesture_n=20,
        tape_eaten=False,
        btc_regime="box",
        card_bearing_verdict="propose",
        b_verdict="propose",
        b_marks_ok=True,
        venue=card.venue,
        spot_acked=False,
    )
    assert strat.propose(snap) is None


def test_p5_ack_opens_rail_but_adapter_does_not_send(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    adapter = SpotAdapter(kn)
    card = from_news(symbol=NEW, now=NOW, calendar=(_listing(),))
    assert adapter.allow(card) is False
    assert adapter.propose(card) is None
    with pytest.raises(ValueError, match="ack"):
        adapter.ack(NEW, ack=False, ts=NOW)
    out = adapter.ack(NEW, ack=True, ts=NOW)
    assert out["acked"] is True
    assert adapter.acked(NEW) is True
    opened = from_news(symbol=NEW, now=NOW, calendar=(_listing(),), spot_acked=True)
    assert opened.venue == "spot_proposal"
    assert opened.bearing_verdict == "propose"
    assert adapter.allow(opened) is True
    assert adapter.propose(opened) is None
    kn.close()


def test_p5_adapter_never_imports_signer() -> None:
    import capitalizator.exec.spot as spot

    assert "signer" not in spot.__dict__
    text = Path(spot.__file__).read_text(encoding="utf-8")
    assert "capitalizator.signer" not in text
