"""P8 — allow-list pump. Empty book is honest. TG and sole whale never enter."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from capitalizator.authors.pump import FetchedItem, pump
from capitalizator.authors.score import author_accepts
from capitalizator.authors.sources import SourceBook, SourcesError, load_sources
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.whales.no_single import sole_whale, whale_accepts
from capitalizator.zones.model import Zone

NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)


def _book(tmp_path: Path, *, sources: list[dict] | None = None) -> SourceBook:
    path = tmp_path / "sources.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "allowed_kinds": ["rss", "reddit_json", "tradingview_own"],
                "forbidden_kinds": ["telegram", "scrape", "tip"],
                "sources": sources or [],
            }
        ),
        encoding="utf-8",
    )
    return load_sources(path)


def _item(
    *,
    source_id: str = "fed",
    title: str = "FOMC minutes",
    url: str = "https://www.federalreserve.gov/a",
) -> FetchedItem:
    return FetchedItem(
        source_id=source_id,
        kind="rss",
        url=url,
        title=title,
        body=title,
        known_at=NOW,
    )


def test_p8_repo_sources_stay_empty() -> None:
    assert load_sources().sources == ()


def test_p8_empty_book_returns_none(tmp_path: Path) -> None:
    book = _book(tmp_path)
    assert pump(symbol="BTCUSDT", now=NOW, book=book, fetched=()) is None


def test_p8_telegram_source_refused(tmp_path: Path) -> None:
    with pytest.raises(SourcesError, match="forbidden"):
        _book(
            tmp_path,
            sources=[
                {
                    "id": "tg",
                    "kind": "telegram",
                    "url": "https://t.me/x",
                    "tos_ok": True,
                }
            ],
        )


def test_p8_telegram_item_url_refused(tmp_path: Path) -> None:
    book = _book(
        tmp_path,
        sources=[
            {
                "id": "fed",
                "kind": "rss",
                "url": "https://www.federalreserve.gov/feed",
                "tos_ok": True,
            }
        ],
    )
    with pytest.raises(ValueError, match="telegram"):
        pump(
            symbol="BTCUSDT",
            now=NOW,
            book=book,
            fetched=(_item(url="https://t.me/channel"),),
        )


def test_p8_author_hit_is_propose_but_never_accept(tmp_path: Path) -> None:
    book = _book(
        tmp_path,
        sources=[
            {
                "id": "fed",
                "kind": "rss",
                "url": "https://www.federalreserve.gov/feed",
                "tos_ok": True,
            }
        ],
    )
    card = pump(symbol="BTCUSDT", now=NOW, book=book, fetched=(_item(),))
    assert card is not None
    assert card.bearing_verdict == "propose"
    assert "author_never_accept" in card.minuses
    assert author_accepts(has_zone=True) is False
    assert whale_accepts() is False


def test_p8_sole_whale_is_hold(tmp_path: Path) -> None:
    book = _book(
        tmp_path,
        sources=[
            {
                "id": "fed",
                "kind": "rss",
                "url": "https://www.federalreserve.gov/feed",
                "tos_ok": True,
            }
        ],
    )
    item = _item(title="whale wallet 0xabc bought")
    assert sole_whale([{"type": "whale"}]) is True
    card = pump(symbol="BTCUSDT", now=NOW, book=book, fetched=(item,))
    assert card is not None
    assert card.bearing_verdict == "hold"
    assert "whale_only" in card.minuses
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=NOW,
    )
    snap = BounceSnapshot(
        now=NOW,
        symbol="BTCUSDT",
        price=Decimal("100.1"),
        tick=Decimal("0.1"),
        trading_mode="demo",
        zone=zone,
        zones=(zone,),
        jury="ACCORD",
        cav_label="REJECT",
        zlg_label="DEFEND",
        n_cav=20,
        n_zlg=20,
        gesture_n=20,
        tape_eaten=False,
        btc_regime="box",
        card_bearing_verdict="hold",
        b_verdict="hold",
        b_marks_ok=True,
    )
    assert strat.propose(snap) is None


def test_p8_pump_never_imports_signer() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "authors" / "pump.py"
    text = src.read_text(encoding="utf-8")
    assert "capitalizator.signer" not in text
    assert "hl_ingest" not in text
