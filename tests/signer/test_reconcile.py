"""Exchange list wins. A pulled order disappears locally."""

from __future__ import annotations

from capitalizator.risk.session import load_time_config
from capitalizator.signer.reconcile import (
    PaperOrder,
    PaperPosition,
    Reconciler,
    yaml_reconcile_s,
)


def test_interval_comes_from_time_yaml() -> None:
    assert int(load_time_config()["reconcile_s"]) == 60
    assert yaml_reconcile_s() == 60
    assert Reconciler().reconcile_s == 60


def test_missing_on_exchange_is_dropped() -> None:
    rec = Reconciler()
    rec.local["a"] = PaperOrder(order_id="a", symbol="BTCUSDT")
    rec.tick({})
    assert rec.local == {}


def test_exchange_row_is_kept() -> None:
    rec = Reconciler()
    live = PaperOrder(order_id="b", symbol="ETHUSDT")
    rec.tick({"b": live})
    assert rec.local == {"b": live}


def test_empty_exchange_is_not_unknown() -> None:
    rec = Reconciler()
    got = rec.unknown_position([], local_symbol="BTCUSDT")
    assert got.flatten is False
    assert got.halt_entries is False
    assert got.alert is None


def test_matching_local_is_not_unknown() -> None:
    rec = Reconciler()
    got = rec.unknown_position([PaperPosition("BTCUSDT")], local_symbol="BTCUSDT")
    assert got.flatten is False
    assert got.alert is None


def test_exchange_position_without_local_is_critical() -> None:
    rec = Reconciler()
    got = rec.unknown_position([PaperPosition("BTCUSDT")], local_symbol=None)
    assert got.flatten is True
    assert got.halt_entries is True
    assert got.alert == "CRITICAL"


def test_other_symbol_on_exchange_is_critical() -> None:
    rec = Reconciler()
    got = rec.unknown_position([PaperPosition("ETHUSDT")], local_symbol="BTCUSDT")
    assert got.flatten is True
    assert got.alert == "CRITICAL"


def test_extra_symbol_beside_local_is_critical() -> None:
    rec = Reconciler()
    got = rec.unknown_position(
        [PaperPosition("BTCUSDT"), PaperPosition("ETHUSDT")],
        local_symbol="BTCUSDT",
    )
    assert got.flatten is True
    assert got.alert == "CRITICAL"


def test_reconcile_does_not_send_flatten() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "signer" / "reconcile.py"
    body = src.read_text(encoding="utf-8")
    assert "place_order" not in body
    assert "create_order" not in body
