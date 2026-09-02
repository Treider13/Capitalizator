"""Registry: ОКО window facts at 8s, verdict at the bar, jury reads oko_voice once."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.memory.journal import JOURNAL_KEYS
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
VERDICT = dict(
    label="SPOOF",
    regime="RANGE",
    reason="spoof on zone side, book_trust 0.00",
    book_trust="0.0000",
    tape_trust=None,
    cp_prob="0.0500",
    p_bounce="0.5000",
    p_break="0.4000",
    p_die="0.1000",
    pred_set="bounce|break",
    n_class=7,
    size_mult="0",
    fingerprint="0-3-0-0-4-2-4-1-0-0",
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
    reg.fill_cav(cav_label="REJECT")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    return reg


def test_window_facts_then_verdict_then_veto_jury() -> None:
    reg = _reg()
    before = len(reg.chain.links)
    row = reg.fill_oko_window(
        label="SPOOF", fingerprint="0-3-0-0-4-2-4-1-0-0", book_trust="0.0000", tape_trust=None
    )[0]
    assert row.oko_label == "SPOOF"
    assert row.oko_voice is None
    assert len(reg.chain.links) == before
    row = reg.fill_oko(voice="VETO", **VERDICT)[0]
    assert row.oko_voice == "VETO"
    assert row.oko_size_mult == "0"
    assert row.oko_n_class == 7
    stamped = reg.stamp_jury(n_cav=20, n_zlg=20)[0]
    assert stamped.jury == "VETO"
    assert stamped.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"


def test_without_oko_the_jury_is_the_old_five() -> None:
    reg = _reg()
    assert reg.stamp_jury(n_cav=20, n_zlg=20)[0].jury == "ACCORD"


def test_explicit_oko_voice_beats_the_row_and_minus_one_splits() -> None:
    reg = _reg()
    reg.fill_oko(voice=1, **VERDICT)
    assert reg.stamp_jury(n_cav=20, n_zlg=20, oko_voice=-1)[0].jury == "SPLIT"


def test_oko_voice_is_a_fact_not_restamped() -> None:
    reg = _reg()
    first = reg.fill_oko(voice=0, **VERDICT)[0]
    assert first.oko_voice == 0
    assert reg.fill_oko(voice="VETO", **{**VERDICT, "label": "CASCADE"}) == []
    row = reg.touches[0]
    assert row.oko_voice == 0
    assert row.oko_label == "SPOOF"


def test_fill_oko_validates() -> None:
    reg = _reg()
    with pytest.raises(ValueError, match="voice"):
        reg.fill_oko(voice=2, **VERDICT)
    with pytest.raises(ValueError, match="label"):
        reg.fill_oko(voice=0, **{**VERDICT, "label": "WASH"})
    with pytest.raises(ValueError, match="regime"):
        reg.fill_oko(voice=0, **{**VERDICT, "regime": "BULL"})
    with pytest.raises(ValueError, match="size_mult"):
        reg.fill_oko(voice=0, **{**VERDICT, "size_mult": "1.5"})
    with pytest.raises(ValueError, match="n_class"):
        reg.fill_oko(voice=0, **{**VERDICT, "n_class": -1})
    with pytest.raises(ValueError, match="label"):
        reg.fill_oko_window(label="x", fingerprint="0", book_trust=None, tape_trust=None)
    with pytest.raises(ValueError, match="fingerprint"):
        reg.fill_oko_window(label="CLEAN", fingerprint="", book_trust=None, tape_trust=None)


def test_journal_has_the_oko_keys() -> None:
    for key in (
        "oko_voice",
        "oko_label",
        "oko_regime",
        "oko_reason",
        "oko_book_trust",
        "oko_tape_trust",
        "oko_cp_prob",
        "oko_p_bounce",
        "oko_p_break",
        "oko_p_die",
        "oko_set",
        "oko_n_class",
        "oko_size_mult",
        "oko_fingerprint",
    ):
        assert key in JOURNAL_KEYS


def test_two_runs_same_stamp() -> None:
    def run() -> tuple[str | None, object]:
        reg = _reg()
        reg.fill_oko(voice="VETO", **VERDICT)
        row = reg.stamp_jury(n_cav=20, n_zlg=20)[0]
        return row.jury, row.oko_voice

    assert run() == run() == ("VETO", "VETO")
