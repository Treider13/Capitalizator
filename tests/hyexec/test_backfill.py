"""Backfill fills hx_* holes only. r_net stays. Future bars do not leak."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.hyexec.backfill import apply_features, as_of_of, backfill_rows, needs_fill
from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.hyexec.features import build_features, feature_journal
from capitalizator.zones.model import Bar

AS_OF = datetime(2026, 9, 1, 10, 5, tzinfo=UTC)


def _bar(tf: str, close_ts: datetime, close: str) -> Bar:
    minutes = {"1m": 1, "5m": 5, "1h": 60}[tf]
    px = Decimal(close)
    return Bar(
        symbol="BTCUSDT",
        tf=tf,
        open_ts=close_ts - timedelta(minutes=minutes),
        close_ts=close_ts,
        open=px,
        high=px,
        low=px,
        close=px,
        volume=Decimal("1"),
    )


def _labeled_hole() -> dict:
    row = {key: None for key in FEATURE_KEYS}
    row["touch_id"] = "t1"
    row["symbol"] = "BTCUSDT"
    row["touch_ts"] = AS_OF.isoformat()
    row["paper"] = {"shadow": {"filled": True, "r_net": "1.25"}}
    row["hx_close_5m"] = "keep-me"
    return row


def test_as_of_prefers_touch_ts() -> None:
    assert as_of_of({"touch_ts": AS_OF.isoformat()}) == AS_OF
    assert as_of_of({"touch_ts": "nope"}) is None


def test_needs_fill_requires_touch_id_and_a_hole() -> None:
    full = {key: "1" for key in FEATURE_KEYS}
    full["touch_id"] = "t"
    assert needs_fill(full) is False
    hole = {key: "1" for key in FEATURE_KEYS}
    hole["hx_sma5_5m"] = None
    hole["touch_id"] = "t"
    assert needs_fill(hole) is True
    hole.pop("touch_id")
    assert needs_fill(hole) is False


def test_apply_features_keeps_paper_and_existing_hx() -> None:
    row = _labeled_hole()
    stamped = feature_journal(
        build_features(
            bars_1m=(_bar("1m", AS_OF, "100"), _bar("1m", AS_OF - timedelta(minutes=1), "99")),
            bars_5m=(_bar("5m", AS_OF, "100"),),
            bars_1h=(),
            as_of=AS_OF,
        )
    )
    got = apply_features(row, stamped)
    assert got["paper"]["shadow"]["r_net"] == "1.25"
    assert got["hx_close_5m"] == "keep-me"
    assert got["hx_ret_1m"] == stamped["hx_ret_1m"]
    assert got["touch_id"] == "t1"


def test_backfill_rows_drops_future_bars_and_is_idempotent() -> None:
    future = _bar("5m", AS_OF + timedelta(minutes=5), "999")
    past = _bar("5m", AS_OF, "100")

    def bars(symbol: str, when: datetime):
        assert symbol == "BTCUSDT"
        assert when == AS_OF
        return (), (past, future), ()

    first, n = backfill_rows([_labeled_hole()], bars=bars)
    assert n == 1
    assert first[0]["paper"]["shadow"]["r_net"] == "1.25"
    assert first[0]["hx_close_5m"] == "keep-me"
    assert first[0]["hx_high_5m"] == "100"
    second, n2 = backfill_rows(first, bars=bars)
    assert n2 == 0
    assert second[0]["hx_high_5m"] == first[0]["hx_high_5m"]
