"""2.11.7 — propose() applies MacroRules size_mult and blackout. Calendar is real CSV."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.desk.loop import DeskLoop
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.news_macro.ingest import NewsIngest
from capitalizator.news_macro.rules import MacroRules
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.risk.sessions import SessionPolicy
from capitalizator.signer.process import unsigned_from_intent
from capitalizator.zones.model import Zone

MACRO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "macro.csv"
SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
PRE_CPI = datetime(2026, 9, 10, 14, 10, tzinfo=UTC)
FOMC_ET = datetime(2026, 9, 16, 18, 10, tzinfo=UTC)
NFP_MORNING = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class _AlwaysOpen:
    """Isolate MacroRules from the session policy. Not a product session."""

    def allows(self, now_utc, calendar=None, **_kw):
        return True, "test_open"


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


def _strategy(*, session=None, macro: MacroRules | None = None) -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        session=session,
        macro=macro if macro is not None else MacroRules(enabled=True),
    )


def _snap(*, now: datetime, calendar=None, **overrides: object) -> BounceSnapshot:
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
        "calendar": NewsIngest.from_csv(MACRO).rows if calendar is None else calendar,
    }
    raw.update(overrides)
    return BounceSnapshot(**raw)  # type: ignore[arg-type]


def test_desk_passes_enabled_macro_to_strategy(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "desk")))
    assert desk.macro.enabled is True
    assert desk.strategy.macro is desk.macro


def test_pre_cpi_intent_size_mult_is_half() -> None:
    got = _strategy().propose(_snap(now=PRE_CPI))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("0.5")


def test_quiet_session_intent_size_mult_is_one() -> None:
    got = _strategy().propose(_snap(now=SESSION))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("1")


def test_b_macro_multiplier_lands_on_size_mult() -> None:
    got = _strategy().propose(
        _snap(now=SESSION, b_verdict="cut_size", macro_multiplier=Decimal("0.3"))
    )
    assert isinstance(got, Intent)
    assert got.qty is None
    assert got.size_mult == Decimal("0.3")


def test_macro_off_does_not_cut_pre_cpi() -> None:
    got = _strategy(macro=MacroRules(enabled=False)).propose(_snap(now=PRE_CPI))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("1")


def test_fomc_et_blackout_is_macro_not_session() -> None:
    """14:10 ET on FOMC day: MacroRules says et_blackout regardless of the session window."""
    cal = NewsIngest.from_csv(MACRO).rows
    ok, why = SessionPolicy.load().allows(FOMC_ET, cal, idea="bounce", symbol="BTCUSDT")
    assert ok or why.startswith(("us_data_day", "window"))
    assert MacroRules(enabled=True).decide(FOMC_ET, cal).reason == "et_blackout"
    assert _strategy(session=_AlwaysOpen()).propose(_snap(now=FOMC_ET)) is None
    open_day = _strategy(session=_AlwaysOpen()).propose(_snap(now=FOMC_ET, calendar=()))
    assert isinstance(open_day, Intent)
    assert open_day.size_mult == Decimal("1")


def test_nfp_morning_blocked_by_calendar_not_clock() -> None:
    """no_us_today opens a quiet morning; NFP row still closes via us_data_day."""
    quiet = _strategy().propose(_snap(now=NFP_MORNING, calendar=(), no_us_today=True))
    assert isinstance(quiet, Intent)
    assert _strategy().propose(_snap(now=NFP_MORNING, no_us_today=True)) is None


def test_signer_applies_intent_size_mult() -> None:
    raw = unsigned_from_intent(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "entry": "100.5",
            "stop": "99.2",
            "tp": "103.1",
            "tag": "bounce",
            "size_mult": "0.5",
        },
        allow_default_qty=True,
    )
    assert raw.qty == Decimal("0.0005")


def test_signer_rejects_zero_size_mult() -> None:
    with pytest.raises(ValueError, match="size_mult"):
        unsigned_from_intent(
            {
                "symbol": "BTCUSDT",
                "side": "buy",
                "entry": "100.5",
                "stop": "99.2",
                "tp": "103.1",
                "size_mult": 0,
            },
            allow_default_qty=True,
        )
