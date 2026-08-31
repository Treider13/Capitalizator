"""Journal width / quality / hour. Not a voice, not class_id, not a hash link."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.memory.registry import Registry
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _reg() -> Registry:
    reg = Registry(tick_size=TICK)
    trade = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=PRINT,
        recv_ts=PRINT,
        seq=None,
        payload={"px": "100.1", "qty": "0.001", "side": "buy"},
    )
    assert len(reg.on_trade(trade, [ZONE])) == 1
    return reg


def test_fill_width_and_quality_and_hour() -> None:
    reg = _reg()
    before = len(reg.chain.links)
    w = reg.fill_width(w_now=Decimal("1.5"), w_rank=Decimal("0.4"))
    q = reg.fill_bar_quality(quality="live")
    h = reg.fill_session_hour()
    assert w[0].w_now == Decimal("1.5")
    assert w[0].w_rank == Decimal("0.4")
    assert q[0].bar_quality == "live"
    assert h[0].session_hour == 16
    assert len(reg.chain.links) == before
    assert reg.chain.verify() is True


def test_journal_does_not_change_class_id() -> None:
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    reg.fill_width(w_now=Decimal("2"), w_rank=Decimal("0.9"))
    reg.fill_bar_quality(quality="stagnant")
    reg.fill_session_hour()
    row = reg.stamp_jury(n_cav=20, n_zlg=20)[0]
    assert row.jury == "ACCORD"
    assert row.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"
    assert "16" not in row.rho_class_id
    assert "stagnant" not in row.rho_class_id
    assert "0.9" not in row.rho_class_id


def test_unknown_quality_rejected() -> None:
    reg = _reg()
    with pytest.raises(ValueError, match="bar_quality"):
        reg.fill_bar_quality(quality="gap")


def test_w_rank_outside_unit_rejected() -> None:
    reg = _reg()
    with pytest.raises(ValueError, match="w_rank"):
        reg.fill_width(w_now=Decimal("1"), w_rank=Decimal("1.1"))
    with pytest.raises(ValueError, match="w_now"):
        reg.fill_width(w_now=Decimal("-0.1"), w_rank=None)


def test_two_runs_same_journal() -> None:
    def run() -> tuple[Decimal | None, str | None, int | None, str | None]:
        reg = _reg()
        reg.fill_width(w_now=Decimal("1.25"), w_rank=None)
        reg.fill_bar_quality(quality="illiquid")
        reg.fill_session_hour()
        row = reg.touches[0]
        return row.w_now, row.bar_quality, row.session_hour, row.rho_class_id

    assert run() == run()
    assert run() == (Decimal("1.25"), "illiquid", 16, None)
