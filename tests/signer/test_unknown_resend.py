"""A transport failure is not a refusal. When the venue says the order never arrived and
the intent is still valid, the signer re-sends it under the same orderLinkId (the venue
de-duplicates); a bounded number of times, then the honest verdict.

Before: `not_on_venue` → `rejected` — the idea was freed and the trade silently lost.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from capitalizator.gateway.bybit import order_link_id
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.signer.process import RESEND_MAX, resolve_unknown_intents

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

_spec = importlib.util.spec_from_file_location(
    "gw_fixture", Path(__file__).resolve().parents[1] / "gateway" / "test_gateway.py"
)
assert _spec is not None and _spec.loader is not None
_gwmod = importlib.util.module_from_spec(_spec)
sys.modules["gw_fixture"] = _gwmod
_spec.loader.exec_module(_gwmod)
FakeSession, _gw, _intent = _gwmod.FakeSession, _gwmod._gw, _gwmod._intent


def _unknown_row(kn, payload: dict) -> int:  # noqa: ANN001
    iid = kn.enqueue_intent(payload, created_ts=NOW.isoformat())
    kn.mark_intent(iid, "unknown", {"orderLinkId": order_link_id(payload),
                                   "symbol": payload["symbol"], "error": "network"})
    return iid


def test_absent_on_venue_and_still_valid_is_resent(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    gw = _gw(s)
    payload = _intent(touch_id="t-resend")
    iid = _unknown_row(kn, payload)
    out = resolve_unknown_intents(kn, gw, now=NOW)
    assert out == [{"id": iid, "status": "sent", "resend_attempts": 1}]
    link = order_link_id(payload)
    assert link in s.orders  # the very same link id went to the venue
    placed = [c for c in s.calls if c[0] == "place_order"]
    assert len(placed) == 1 and placed[0][1]["orderLinkId"] == link
    rows = kn.intents_with_status("sent")
    assert [r["id"] for r in rows] == [iid]
    assert rows[0]["result"]["resend_attempts"] == 1
    assert kn.order_rows(limit=5)  # the accepted resend is an order row like any send


def test_absent_but_stale_is_rejected_not_resent(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    gw = _gw(s)
    payload = _intent(touch_id="t-stale", valid_until=(NOW - timedelta(minutes=1)).isoformat())
    iid = _unknown_row(kn, payload)
    out = resolve_unknown_intents(kn, gw, now=NOW)
    assert out[0]["id"] == iid and out[0]["status"] == "rejected"
    assert [c for c in s.calls if c[0] == "place_order"] == []
    assert kn.intents_with_status("rejected")[0]["result"]["reason"] == "stale_intent"


def test_network_keeps_failing_bounded_then_honest_rejection(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    gw = _gw(s)
    payload = _intent(touch_id="t-flaky")
    iid = _unknown_row(kn, payload)
    for attempt in range(1, RESEND_MAX + 1):
        s.fail_next = "place_order"
        out = resolve_unknown_intents(kn, gw, now=NOW)
        assert out == [{"id": iid, "status": "unknown", "resend_attempts": attempt}]
    # attempts exhausted: the next pass does not send again and says why
    out = resolve_unknown_intents(kn, gw, now=NOW)
    assert out == [{"id": iid, "status": "rejected", "resend_attempts": RESEND_MAX}]
    res = kn.intents_with_status("rejected")[0]["result"]
    assert res["reason"] == "not_on_venue_after_resend"
    assert len([c for c in s.calls if c[0] == "place_order"]) == RESEND_MAX


def test_order_found_on_venue_is_sent_without_resend(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    gw = _gw(s)
    payload = _intent(touch_id="t-there")
    link = order_link_id(payload)
    s.orders[link] = {"orderLinkId": link, "orderId": "oid-1", "orderStatus": "New"}
    iid = _unknown_row(kn, payload)
    out = resolve_unknown_intents(kn, gw, now=NOW)
    assert out == [{"id": iid, "status": "sent"}]
    assert [c for c in s.calls if c[0] == "place_order"] == []
