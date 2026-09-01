"""propose() must copy MacroRules.size_mult onto Intent (§11 / 2.11.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.news_macro.ingest import NewsIngest
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
WINDOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
PRE_CPI = datetime(2026, 9, 10, 14, 10, tzinfo=UTC)
MACRO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "macro.csv"
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _strat() -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )


def _snap(**overrides: object) -> BounceSnapshot:
    raw: dict[str, object] = {
        "now": WINDOW,
        "symbol": "BTCUSDT",
        "price": Decimal("100.5"),
        "tick": TICK,
        "trading_mode": "demo",
        "zone": ZONE,
        "zones": (ZONE,),
        "spread_frac": Decimal("0.001"),
        "typical_move": Decimal("0.01"),
        "idea": "bounce",
        "jury": "ACCORD",
        "cav_label": "REJECT",
        "zlg_label": "DEFEND",
        "n_cav": 20,
        "n_zlg": 20,
        "tape_eaten": False,
        "btc_regime": "box",
        "gesture_n": 20,
        "card_bearing_verdict": "VERIFIED",
    }
    raw.update(overrides)
    return BounceSnapshot(**raw)  # type: ignore[arg-type]


def test_ordinary_day_size_mult_is_one() -> None:
    got = _strat().propose(_snap())
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("1")


def test_cpi_pre_event_halves_size_mult() -> None:
    news = NewsIngest.from_csv(MACRO)
    got = _strat().propose(_snap(now=PRE_CPI, calendar=news.rows))
    assert isinstance(got, Intent)
    assert got.size_mult == Decimal("0.5")
