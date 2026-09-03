"""3.13.3 — DEFEND after a puncture is fake_defend, not a chase."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.exec.breakout_gesture import FAKE_DEFEND, skip_reason
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.zones.model import Zone

SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
)


def test_defend_after_close_beyond_is_fake_defend() -> None:
    assert skip_reason(gesture="DEFEND", close_beyond=True) == FAKE_DEFEND


def test_retreat_after_close_is_not_this_skip() -> None:
    assert skip_reason(gesture="RETREAT", close_beyond=True) is None


def test_defend_without_puncture_is_not_fake() -> None:
    assert skip_reason(gesture="DEFEND", close_beyond=False) is None


def test_breakout_defend_close_beyond_is_fake_defend() -> None:
    nxt = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("96"),
        hi=Decimal("96.6"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )
    s = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
    )
    got = s.propose(
        BounceSnapshot(
            now=SESSION,
            symbol="BTCUSDT",
            price=Decimal("100.5"),
            tick=Decimal("0.1"),
            trading_mode="demo",
            zone=ZONE,
            zones=(ZONE, nxt),
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            idea="breakout",
            allow_break=True,
            close_beyond=True,
            tape_eaten=True,
            first_minute=False,
            cav_label="THROUGH",
            zlg_label="DEFEND",
            n_cav=20,
            n_zlg=20,
            gesture_n=20,
            btc_regime="box",
            jury="ACCORD",
            next_target=nxt,
        )
    )
    assert got is None
    assert s.last_skip == "breakout:fake_defend"
