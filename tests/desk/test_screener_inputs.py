"""D-15: screener flags the desk used to pass as constants are now computed."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.instruments import Instrument
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _funding(symbol: str, rate: str, i: int) -> MarketEvent:
    return MarketEvent(stream="funding", exchange="bybit", symbol=symbol, exchange_ts=T0,
                       recv_ts=T0, payload={"funding": rate})


def test_funding_extreme_is_own_95th_percentile_after_min_n(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off")
    assert desk._funding_extreme("BTCUSDT") is False  # unknown is not extreme
    for i in range(25):
        desk.on_event(_funding("BTCUSDT", f"0.0001{i % 7}", i))
        desk._funding_extreme("BTCUSDT")
    assert desk._funding_extreme("BTCUSDT") is False  # inside its own distribution
    desk.on_event(_funding("BTCUSDT", "0.0035", 99))  # near the ±0.375% clamp
    assert desk._funding_extreme("BTCUSDT") is True


def test_delisted_comes_from_instrument_status(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off")
    inst = Instrument(symbol="BTCUSDT", tick=Decimal("0.1"), qty_step=Decimal("0.001"),
                      min_qty=Decimal("0.001"), min_notional=Decimal("5"), max_lev=Decimal("100"),
                      funding_interval_min=480, status="Delivering", source="test")
    desk.instruments.put(inst)
    assert desk._instrument_for("BTCUSDT").trading is False
