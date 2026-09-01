"""2.11.7 — propose() applies MacroRules size_mult and blackout. Calendar is real CSV."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.news_macro.ingest import NewsIngest
from capitalizator.news_macro.rules import MacroRules
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.zones.model import Zone

MACRO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "macro.csv"
SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
PRE_CPI = datetime(2026, 9, 10, 14, 10, tzinfo=UTC)
FOMC_ET = datetime(2026, 9, 16, 18, 10, tzinfo=UTC)
NFP_MORNING = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


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


def _strategy() -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        macro=MacroRules(enabled=True),
    )


def _snap(*, now: datetime, **overrides: object) -> BounceSnapshot:
    zone = _zone()
    raw: dict[str, object] = {
        "now": now,
        "symbol": "BTCUSDT",
        "price": Decimal("100.5"),
        "tick": Decimal("0.1"),
        "trading_mode": "demo",
        "zone": zone,
        "zones": (zone,),
        "spread_frac": Decimal("0.001"),
        "typical_move": Decimal("0.01"),
        "calendar": NewsIngest.from_csv(MACRO).rows,
    }
    raw.update(overrides)
    return BounceSnapshot(**raw)  # type: ignore[arg-type]


def test_pre_cpi_intent_size_mult_is_half() -> None:
    got = _strategy().propose(_snap(now=PRE_CPI))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("0.5")


def test_quiet_session_intent_size_mult_is_one() -> None:
    got = _strategy().propose(_snap(now=SESSION))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("1")


def test_fomc_et_blackout_propose_is_none() -> None:
    """14:10 ET on FOMC day is outside MSK window; no_us_today still hits MacroRules."""
    assert _strategy().propose(_snap(now=FOMC_ET, no_us_today=True)) is None


def test_nfp_morning_outside_us_session_is_none() -> None:
    assert _strategy().propose(_snap(now=NFP_MORNING)) is None


def test_signer_applies_intent_size_mult() -> None:
    from capitalizator.signer.process import unsigned_from_intent

    raw = unsigned_from_intent(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "entry": "100.5",
            "stop": "99.2",
            "tp": "103.1",
            "tag": "bounce",
            "size_mult": "0.5",
        }
    )
    assert raw.qty == Decimal("0.0005")
