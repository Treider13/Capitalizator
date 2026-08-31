"""1.6.1 — all five gates must pass. propose does not send."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.zones.model import Zone

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec" / "strategy_bounce.py"
SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
OUTSIDE = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _zone(*, side: str = "support", lo: str = "100", hi: str = "101") -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side=side,  # type: ignore[arg-type]
        lo=Decimal(lo),
        hi=Decimal(hi),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )


def _strategy() -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
    )


def _snap(**overrides: object) -> BounceSnapshot:
    zone = _zone()
    raw: dict[str, object] = {
        "now": SESSION,
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


def test_all_gates_open_returns_bounce_intent() -> None:
    got = _strategy().propose(_snap())
    assert isinstance(got, Intent)
    assert got.tag == "bounce"
    assert got.side == "buy"
    assert got.stop == Decimal("99.2")
    assert got.stop < got.entry < got.tp


def test_phase_off_returns_none() -> None:
    assert _strategy().propose(_snap(trading_mode="off")) is None


def test_phase_yaml_off_blocks_injected_snapshot_demo() -> None:
    """Current infra/phase.yaml is off. Default constructor must not emit."""
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
    )
    assert strat.desk_mode == "off"
    assert strat.propose(_snap(trading_mode="demo")) is None


def test_outside_session_returns_none() -> None:
    assert _strategy().propose(_snap(now=OUTSIDE)) is None


def test_open_position_returns_none() -> None:
    risk = RiskEngine()
    risk.on_open(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "entry": "100",
            "stop": "99",
            "tp": "102",
            "tag": "bounce",
        }
    )
    strat = BounceStrategy(
        risk=risk,
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
    )
    assert strat.propose(_snap()) is None


def test_halt_returns_none() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.mark_liq()
    strat = BounceStrategy(risk=RiskEngine(), halts=h, desk_mode="demo")
    assert strat.propose(_snap()) is None


def test_wide_spread_returns_none() -> None:
    assert (
        _strategy().propose(_snap(spread_frac=Decimal("0.004"), typical_move=Decimal("0.003")))
        is None
    )


def test_price_outside_zone_returns_none() -> None:
    zone = _zone()
    assert _strategy().propose(_snap(price=Decimal("105"), zone=zone, zones=(zone,))) is None


def test_no_zone_returns_none() -> None:
    assert _strategy().propose(_snap(zone=None, zones=())) is None


def test_source_does_not_submit() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "submit" not in text
    assert "place_order" not in text
    assert "api.bybit.com" not in text


def test_resistance_zone_is_a_short() -> None:
    zone = _zone(side="resistance", lo="109", hi="110")
    got = _strategy().propose(
        _snap(price=Decimal("109.5"), zone=zone, zones=(zone,))
    )
    assert got is not None
    assert got.side == "sell"
    assert got.stop == Decimal("110.8")
    assert got.tp < got.entry < got.stop


def test_next_zone_closer_than_one_point_five_r_is_none() -> None:
    zone = _zone()
    nxt = _zone(side="resistance", lo="102", hi="103")
    assert (
        _strategy().propose(_snap(zone=zone, zones=(zone, nxt), next_target=nxt))
        is None
    )
