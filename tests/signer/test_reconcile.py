"""Exchange list wins. A pulled order disappears locally."""

from __future__ import annotations

from capitalizator.signer.reconcile import PaperOrder, Reconciler


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
