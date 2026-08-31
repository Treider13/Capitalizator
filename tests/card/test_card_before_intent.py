"""Default propose requires a card file. Missing card → no intent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.card.draft import apply_bind, require_card
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.verifier.manual import ManualVerifier
from capitalizator.zones.model import Zone


def _zone() -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )


def _snap(**overrides: object) -> BounceSnapshot:
    zone = _zone()
    raw: dict[str, object] = {
        "now": datetime(2026, 8, 31, 14, 10, tzinfo=UTC),
        "symbol": "BTCUSDT",
        "price": Decimal("100.5"),
        "tick": Decimal("0.1"),
        "trading_mode": "demo",
        "zone": zone,
        "zones": (zone,),
        "spread_frac": Decimal("0.001"),
        "typical_move": Decimal("0.01"),
    }
    raw.update(overrides)
    return BounceSnapshot(**raw)  # type: ignore[arg-type]


def _strat(**kwargs: object) -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        **kwargs,  # type: ignore[arg-type]
    )


def test_missing_card_rejects_by_default() -> None:
    assert _strat().require_card is True
    assert _strat().check_load_bearing is True
    assert _strat().propose(_snap()) is None


def test_pending_card_file_alone_is_not_enough(tmp_path: Path) -> None:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC).isoformat()
    payload = {
        "thesis": "unit fixture, not a market call",
        "claims": [
            {
                "type": "unit",
                "subject": "BTCUSDT",
                "value": f"fixture-{i}",
                "as_of": stamp,
                "known_at": stamp,
                "horizon": "1h",
                "load_bearing": i == 0,
            }
            for i in range(5)
        ],
    }
    path = tmp_path / "card.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    got = _strat().propose(_snap(card_path=path))
    assert got is None


def test_stamped_after_bind_allows_propose(tmp_path: Path) -> None:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC).isoformat()
    payload = {
        "thesis": "unit fixture, not a market call",
        "claims": [
            {
                "type": "unit",
                "subject": "BTCUSDT",
                "value": f"fixture-{i}",
                "as_of": stamp,
                "known_at": stamp,
                "horizon": "1h",
                "load_bearing": i == 0,
            }
            for i in range(5)
        ],
    }
    path = tmp_path / "card.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    card = require_card(path, required=True)
    assert card is not None
    q = tmp_path / "q.txt"
    q.write_text(card.claims[0].value + "\n", encoding="utf-8")
    receipt = ManualVerifier().bind(card.claims[0].value, q, card.claims[0].value)
    assert receipt.verdict == "VERIFIED"
    stamped = apply_bind(card, 0, receipt)
    got = _strat().propose(_snap(card=stamped))
    assert got is not None
    assert got.tag == "bounce"


def test_pending_bearing_blocks_when_check_on(tmp_path: Path) -> None:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC).isoformat()
    payload = {
        "thesis": "unit fixture",
        "claims": [
            {
                "type": "unit",
                "subject": "BTCUSDT",
                "value": f"fixture-{i}",
                "as_of": stamp,
                "known_at": stamp,
                "horizon": "1h",
                "load_bearing": i == 0,
                "verdict": "pending",
            }
            for i in range(5)
        ],
    }
    path = tmp_path / "card.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    got = _strat(check_load_bearing=True).propose(_snap(card_path=path))
    assert got is None
