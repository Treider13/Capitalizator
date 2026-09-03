"""The BTC bus carries the *direction* of the HTF trend, so «same side as BTC» is a fact.

Before: `BtcRegime` collapsed long/short into "trend" and the desk set
`btc_same_side = regime == "box"` — an alt long during a BTC 4h uptrend earned nothing,
and the jury's +1 for BTC existed only in a range.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.zones.model import Bar

TICK = Decimal("0.1")
DAY = datetime(2026, 8, 30, tzinfo=UTC)


def _h4(hour: int, high: str, low: str, close: str) -> Bar:
    return Bar(symbol="BTCUSDT", tf="4h", open_ts=DAY.replace(hour=hour),
               close_ts=DAY.replace(hour=hour + 4), open=Decimal(close), high=Decimal(high),
               low=Decimal(low), close=Decimal(close))


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off",
                    tick_size=TICK)


def test_uptrend_publishes_long_direction(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    for bar in (_h4(0, "10", "8", "9"), _h4(4, "11", "8", "10"), _h4(8, "20", "12", "19")):
        desk.on_bar_close(bar)
    assert desk.btc.regime == "trend"
    assert desk.btc.direction == "long"
    assert desk.btc_same_side("buy") is True
    assert desk.btc_same_side("sell") is False


def test_downtrend_publishes_short_direction(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    for bar in (_h4(0, "10", "8", "9"), _h4(4, "11", "8", "10"), _h4(8, "9", "5", "6")):
        desk.on_bar_close(bar)
    assert desk.btc.direction == "short"
    assert desk.btc_same_side("sell") is True
    assert desk.btc_same_side("buy") is False


def test_box_has_no_direction_but_is_same_side_for_both(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    for bar in (_h4(0, "10", "8", "9"), _h4(4, "11", "8", "10"), _h4(8, "10.5", "8.5", "9.5")):
        desk.on_bar_close(bar)
    assert desk.btc.regime == "box"
    assert desk.btc.direction is None
    assert desk.btc_same_side("buy") is True and desk.btc_same_side("sell") is True


def test_unknown_htf_is_neither(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    assert desk.btc.regime is None and desk.btc.direction is None
    assert desk.btc_same_side("buy") is False and desk.btc_same_side("sell") is False
