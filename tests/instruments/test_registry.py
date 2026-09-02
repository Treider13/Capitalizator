"""Per-symbol tick from instruments-info. Unknown symbol is refused, not 0.1."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.desk.loop import DeskLoop
from capitalizator.instruments import (
    Instrument,
    InstrumentRegistry,
    InstrumentUnknown,
    instrument_from_bybit,
    load_snapshot,
)
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.types import MarketEvent

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)

# Shape from https://bybit-exchange.github.io/docs/v5/market/instrument
BYBIT_ROW = {
    "symbol": "DOGEUSDT",
    "status": "Trading",
    "priceFilter": {"minPrice": "0.00001", "maxPrice": "199.99998", "tickSize": "0.00001"},
    "lotSizeFilter": {
        "maxOrderQty": "40000000",
        "minOrderQty": "1",
        "qtyStep": "1",
        "minNotionalValue": "5",
    },
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "75.00", "leverageStep": "0.01"},
    "fundingInterval": 480,
}


def test_snapshot_has_btc_and_eth_only_confirmed_rows() -> None:
    rows = load_snapshot()
    assert rows["BTCUSDT"].tick == Decimal("0.1")
    assert rows["BTCUSDT"].qty_step == Decimal("0.001")
    assert rows["BTCUSDT"].min_notional == Decimal("5")
    assert rows["ETHUSDT"].tick == Decimal("0.01")
    assert "DOGEUSDT" not in rows


def test_bybit_row_maps_every_field() -> None:
    inst = instrument_from_bybit(BYBIT_ROW, fetched_at=NOW)
    assert inst.tick == Decimal("0.00001")
    assert inst.qty_step == Decimal("1")
    assert inst.min_qty == Decimal("1")
    assert inst.min_notional == Decimal("5")
    assert inst.max_lev == Decimal("75.00")
    assert inst.funding_interval_min == 480
    assert inst.trading is True
    assert inst.source == "bybit"


def test_bad_row_is_error_not_default() -> None:
    with pytest.raises(ValueError):
        instrument_from_bybit({"symbol": "X"}, fetched_at=NOW)


def test_refresh_uses_injected_fetch_and_keeps_snapshot_on_error() -> None:
    reg = InstrumentRegistry.offline()
    assert reg.refresh() == 0  # no fetch injected
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("403 from datacenter ip")
        return [BYBIT_ROW]

    reg = InstrumentRegistry(load_snapshot(), fetch=fetch)
    assert reg.refresh(now=NOW) == 0
    assert reg.last_error and "403" in reg.last_error
    assert reg.has("BTCUSDT") and not reg.has("DOGEUSDT")
    assert reg.refresh(now=NOW) == 1
    assert reg.last_error is None
    assert reg.tick("DOGEUSDT") == Decimal("0.00001")
    snap = reg.to_snapshot()
    assert snap["instruments"]["DOGEUSDT"]["tick"] == "0.00001"
    assert snap["fetched_at"] == NOW.isoformat()


def test_round_and_qty_ok() -> None:
    inst = instrument_from_bybit(BYBIT_ROW, fetched_at=NOW)
    assert inst.round_price(Decimal("0.123456")) == Decimal("0.12345")
    assert inst.round_qty(Decimal("123.7")) == Decimal("123")
    ok, why = inst.qty_ok(Decimal("10"), Decimal("0.1"))
    assert ok is False and "minNotional" in why
    ok, _ = inst.qty_ok(Decimal("100"), Decimal("0.1"))
    assert ok is True


def test_desk_strict_mode_refuses_unknown_symbol(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off")  # no tick_size → strict
    assert desk.tick_for("BTCUSDT") == Decimal("0.1")
    assert desk.tick_for("ETHUSDT") == Decimal("0.01")
    with pytest.raises(InstrumentUnknown):
        desk.tick_for("DOGEUSDT")
    out = desk.on_event(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="DOGEUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "0.15", "qty": "100", "side": "sell"},
        )
    )
    assert out == [{"event": "refused", "symbol": "DOGEUSDT", "reason": "instrument_unknown"}]
    assert desk.refused_symbols == {"DOGEUSDT": "instrument_unknown"}
    assert "DOGEUSDT" not in desk.symbols


def test_desk_legacy_tick_only_when_given_explicitly(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="off", tick_size=Decimal("0.5"))
    assert desk.tick_for("DOGEUSDT") == Decimal("0.5")  # fixture fallback
    assert desk.tick_for("ETHUSDT") == Decimal("0.01")  # registry still wins when known
    assert desk.state_for("ETHUSDT").book.tick_size == Decimal("0.01")


def test_registry_put_fixture() -> None:
    reg = InstrumentRegistry()
    reg.put(Instrument.fixture("XRPUSDT", tick="0.0001"))
    assert reg.tick("XRPUSDT") == Decimal("0.0001")
    assert reg.get("XRPUSDT").source == "fixture"
