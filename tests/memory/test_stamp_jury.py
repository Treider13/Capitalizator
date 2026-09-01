"""Jury stamp writes a label. Missing CAV/ZLG → SILENCE. Two runs match."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    opened = reg.on_trade(trade, [ZONE])
    assert len(opened) == 1
    return reg


def test_empty_labels_stamp_silence() -> None:
    reg = _reg()
    changed = reg.stamp_jury()
    assert [row.jury for row in changed] == ["SILENCE"]
    assert changed[0].rho_class_id is None


def test_reject_defend_n20_box_stamps_accord() -> None:
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    changed = reg.stamp_jury(n_cav=20, n_zlg=20)
    assert changed[0].jury == "ACCORD"
    assert changed[0].rho_class_id == "bounce × REJECT × DEFEND × BTC_box"


def test_through_defend_stamps_split() -> None:
    reg = _reg()
    reg.fill_cav(cav_label="THROUGH")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    changed = reg.stamp_jury(n_cav=20, n_zlg=20)
    assert changed[0].jury == "SPLIT"


def test_stamp_jury_does_not_restamp() -> None:
    """Jury is a fact. A later n≥20 must not rewrite an already stamped card."""
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    first = reg.stamp_jury()[0]
    assert first.jury == "SILENCE"
    assert reg.stamp_jury(n_cav=20, n_zlg=20) == []
    assert reg.touches[0].jury == "SILENCE"


def test_fill_and_stamp_need_touch_id_when_several() -> None:
    """One fill must not overwrite another row. _patch without pin paints all."""
    later = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("101"),
        hi=Decimal("101.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    reg = _reg()
    second = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=PRINT + timedelta(seconds=30),
        recv_ts=PRINT + timedelta(seconds=30),
        seq=None,
        payload={"px": "101.1", "qty": "0.001", "side": "buy"},
    )
    assert len(reg.on_trade(second, [ZONE, later])) == 1
    first_id = reg.touches[0].touch_id
    with pytest.raises(ValueError, match="touch_id"):
        reg.fill_gesture(gesture="DEFEND")
    with pytest.raises(ValueError, match="touch_id"):
        reg.fill_cav(cav_label="REJECT")
    with pytest.raises(ValueError, match="touch_id"):
        reg.stamp_jury()
    assert reg.touches[0].gesture is None
    assert reg.touches[1].gesture is None
    reg.fill_gesture(gesture="DEFEND", touch_id=first_id)
    assert reg.touches[0].gesture == "DEFEND"
    assert reg.touches[1].gesture is None


def test_fill_does_not_overwrite_a_written_label() -> None:
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    assert reg.fill_cav(cav_label="THROUGH") == []
    assert reg.touches[0].cav_label == "REJECT"
    reg.fill_btc(regime="box")
    assert reg.fill_btc(regime="news") == []
    assert reg.touches[0].btc_regime == "box"


def test_two_runs_same_jury() -> None:
    def run() -> tuple[str | None, str | None]:
        reg = _reg()
        reg.fill_cav(cav_label="REJECT")
        reg.fill_gesture(gesture="RETREAT")
        reg.fill_btc(regime="box")
        row = reg.stamp_jury(n_cav=20, n_zlg=20)[0]
        return row.jury, row.rho_class_id

    assert run() == run()
