"""Doors: printed thin gesture is a probe; a close magnet is a scalp, not skip."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.card.first_fact import PROBE_SIZE
from capitalizator.exec.strategy_bounce import (
    MIN_R,
    BounceSnapshot,
    BounceStrategy,
    take_profit,
)
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.zones.model import Zone

SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


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


def _jury() -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )


def _open() -> BounceStrategy:
    return BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
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


def test_thin_defend_sends_probe_not_shadow_skip() -> None:
    strat = _jury()
    got = strat.propose(_snap(n_zlg=8, gesture_n=8, zlg_label="DEFEND"))
    assert isinstance(got, Intent)
    assert strat.last_skip is None
    assert got.size_mult == PROBE_SIZE
    assert got.size_mult < Decimal("1")
    assert got.tag == "bounce"
    assert got.side == "buy"


def test_silence_still_refuses_under_jury() -> None:
    strat = _jury()
    assert strat.propose(_snap(zlg_label="SILENCE", gesture_n=40, n_zlg=40)) is None
    assert strat.last_skip in {"first_fact:shadow_gesture", "jury:label_not_accord"}


def test_missing_gesture_still_shadow() -> None:
    strat = _jury()
    assert strat.propose(_snap(zlg_label=None, gesture_n=8, n_zlg=8, cav_label="REJECT")) is None
    assert strat.last_skip == "first_fact:shadow_gesture"


def test_close_magnet_is_scalp_price_not_none() -> None:
    # entry 100.5, structural stop 99.2 → R=1.3; 1.5R=1.95; magnet at 102 is 1.5 < 1.95
    stop = Decimal("99.2")
    nxt = _zone(side="resistance", lo="102", hi="103")
    tp = take_profit("buy", Decimal("100.5"), stop, nxt, idea="bounce")
    assert tp == Decimal("102")
    assert (tp - Decimal("100.5")) < MIN_R * (Decimal("100.5") - stop)


def test_close_magnet_propose_is_scalp_not_tp_none() -> None:
    zone = _zone()
    nxt = _zone(side="resistance", lo="102", hi="103")
    strat = _open()
    got = strat.propose(_snap(zone=zone, zones=(zone, nxt), next_target=nxt, jury=None))
    assert isinstance(got, Intent)
    assert strat.last_skip is None
    assert got.tag == "scalp"
    assert got.tp == Decimal("102")
    assert got.size_mult <= Decimal("0.70")


def test_breakout_close_magnet_still_none() -> None:
    nxt = _zone(lo="102", hi="103")
    assert (
        take_profit("buy", Decimal("100.5"), Decimal("99.2"), nxt, idea="breakout")
        is None
    )
