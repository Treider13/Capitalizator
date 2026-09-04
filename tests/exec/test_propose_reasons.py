"""`propose` names why it refused. A None without a reason was a blind spot in the journal.

`BounceStrategy.last_skip` is the reason of the last refusal and None after an accepted
proposal; the desk writes it as `send_skip = propose:<reason>`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.zones.model import Zone

SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
NIGHT = datetime(2026, 8, 31, 22, 0, tzinfo=UTC)
ZONE = Zone.create(symbol="BTCUSDT", tf="15m", side="support", lo=Decimal("100"),
                   hi=Decimal("101"), method="prior_day_hl",
                   created_as_of=datetime(2026, 8, 30, tzinfo=UTC))


def _strategy(mode: str = "demo") -> BounceStrategy:
    return BounceStrategy(risk=RiskEngine(), halts=Halts(start_equity=Decimal("100000")),
                          desk_mode=mode, require_card=False)


def _snap(**overrides: object) -> BounceSnapshot:
    raw: dict[str, object] = {
        "now": SESSION, "symbol": "BTCUSDT", "price": Decimal("100.5"), "tick": Decimal("0.1"),
        "trading_mode": "demo", "zone": ZONE, "zones": (ZONE,),
        "spread_frac": Decimal("0.001"), "typical_move": Decimal("0.01"),
    }
    raw.update(overrides)
    return BounceSnapshot(**raw)  # type: ignore[arg-type]


def test_accepted_proposal_clears_the_reason() -> None:
    s = _strategy()
    assert s.propose(_snap()) is not None
    assert s.last_skip is None


def test_each_refusal_carries_its_reason() -> None:
    s = _strategy("off")
    assert s.propose(_snap()) is None and s.last_skip == "mode:not_demo_live"
    s = _strategy()
    assert s.propose(_snap(b_verdict="veto")) is None and s.last_skip == "b:veto"
    assert s.propose(_snap(b_verdict="hold")) is None and s.last_skip == "b:hold"
    assert s.propose(_snap(now=NIGHT)) is None
    assert s.last_skip is not None and s.last_skip.startswith("session:")
    assert s.propose(_snap(spread_frac=Decimal("0.02"))) is None and s.last_skip == "screener"
    assert s.propose(_snap(price=Decimal("150"))) is None and s.last_skip == "price:outside_zone"
    assert s.propose(_snap(oko_voice="VETO")) is None and s.last_skip == "oko:veto"
    # a later accepted call resets it
    assert s.propose(_snap()) is not None and s.last_skip is None


def test_unmeasured_typical_move_passes_the_screen_to_the_ev_gate() -> None:
    s = _strategy()
    assert s.propose(_snap(typical_move=None)) is not None
