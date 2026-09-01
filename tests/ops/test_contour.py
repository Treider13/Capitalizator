"""Contour switch: hours24 gate, no phase.yaml write, observe glue, no size."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from capitalizator.book.reconstruct import Book
from capitalizator.memory.registry import Registry
from capitalizator.ops.contour import (
    ContourNotReady,
    ObserveIn,
    contour_state,
    enable,
    hours24,
    observe,
    observe_if_on,
    status,
)
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.phase import phase_path, trading_mode
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent
from capitalizator.zlg.gesture import BookAdd
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
T0 = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _trade(ts: datetime, *, px: str = "100.1", qty: str = "0.001", side: str = "buy") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": px, "qty": qty, "side": side},
    )


def _gap(start: datetime, end: datetime) -> MarketEvent:
    return MarketEvent(
        stream="gap",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=start,
        recv_ts=end,
        seq=None,
        payload={"ts_from": start.isoformat(), "ts_to": end.isoformat()},
    )


def _write_hours24(tape: Path) -> None:
    sink = ParquetSink(tape)
    end = T0 + timedelta(hours=24)
    sink.write(_trade(T0))
    sink.write(_trade(end))
    sink.write(_gap(T0, end))


def _book() -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=PRINT,
            seq=1,
            bids=(("100.1", "10"), ("99.9", "1")),
            asks=(("100.3", "1"),),
        )
    )
    return book


def _bar(*, close_ts: datetime | None = None) -> Bar:
    end = close_ts or datetime(2026, 8, 30, 16, 15, tzinfo=UTC)
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=end,
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )


def _reg() -> Registry:
    reg = Registry(tick_size=TICK)
    opened = reg.on_trade(_trade(PRINT, qty="4"), [ZONE])
    assert len(opened) == 1
    return reg


def _observe_in() -> ObserveIn:
    return ObserveIn(
        book=_book(),
        trades=[_trade(PRINT, qty="1", side="sell")],
        adds=[
            BookAdd(
                ts=PRINT + timedelta(seconds=1),
                side="bid",
                px=Decimal("100"),
                qty=Decimal("2"),
            )
        ],
        cav_bar=_bar(),
        htf_bias="box",
    )


def test_hours24_empty_is_red() -> None:
    ok, span = hours24([])
    assert ok is False
    assert span is None


def test_hours24_short_span_is_red() -> None:
    ok, span = hours24([_trade(T0), _trade(T0 + timedelta(seconds=10))])
    assert ok is False
    assert span == 10


def test_hours24_unmarked_day_is_red() -> None:
    end = T0 + timedelta(hours=24)
    ok, span = hours24([_trade(T0), _trade(end)])
    assert ok is False
    assert span == 86400


def test_hours24_marked_day_is_green() -> None:
    end = T0 + timedelta(hours=24)
    ok, span = hours24([_trade(T0), _trade(end), _gap(T0, end)])
    assert ok is True
    assert span == 86400


def test_enable_refuses_without_hours24(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    before = phase_path().read_text(encoding="utf-8")
    with pytest.raises(ContourNotReady, match="hours24"):
        enable(vault)
    snap = status(vault)
    assert snap["contour"] == "off"
    assert snap["can_enable"] is False
    assert trading_mode() == "off"
    assert phase_path().read_text(encoding="utf-8") == before


def test_enable_after_hours24_does_not_change_phase(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    _write_hours24(vault.tape)
    before = phase_path().read_text(encoding="utf-8")
    raw_before = yaml.safe_load(before)
    out = enable(vault)
    assert out["ok"] is True
    assert out["contour"] == "on"
    assert out["hours24"] is True
    assert out["trading_mode"] == "off"
    assert out["can_enable"] is False
    assert trading_mode() == "off"
    assert phase_path().read_text(encoding="utf-8") == before
    assert yaml.safe_load(phase_path().read_text(encoding="utf-8")) == raw_before
    again = enable(vault)
    assert again["contour"] == "on"
    assert again["ok"] is True


def test_observe_off_writes_nothing() -> None:
    reg = _reg()
    changed = observe(reg, _observe_in(), contour_on=False)
    assert changed == []
    assert reg.touches[0].jury is None
    assert reg.touches[0].gesture is None
    assert reg.touches[0].cav_label is None


def test_observe_on_fills_all_labels_and_stamps() -> None:
    reg = _reg()
    changed = observe(reg, _observe_in(), contour_on=True)
    assert len(changed) == 1
    row = changed[0]
    assert row.tape_eaten is False
    assert row.gesture == "DEFEND"
    assert row.cav_label == "REJECT"
    assert row.btc_regime == "box"
    assert row.jury == "SILENCE"
    assert row.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"


def test_observe_unclosed_bar_is_noise() -> None:
    """CAV: close_ts >= touch.ts → NOISE. We do not wait for a future close."""
    reg = _reg()
    inp = ObserveIn(
        book=_book(),
        trades=[_trade(PRINT, qty="1", side="sell")],
        adds=[
            BookAdd(
                ts=PRINT + timedelta(seconds=1),
                side="bid",
                px=Decimal("100"),
                qty=Decimal("2"),
            )
        ],
        cav_bar=_bar(close_ts=PRINT),
        htf_bias="box",
    )
    row = observe(reg, inp, contour_on=True)[0]
    assert row.cav_label == "NOISE"
    assert row.jury == "SILENCE"


def test_observe_two_runs_match() -> None:
    def run() -> tuple[str | None, str | None, str | None, str | None]:
        reg = _reg()
        row = observe(reg, _observe_in(), contour_on=True)[0]
        return row.gesture, row.cav_label, row.jury, row.rho_class_id

    assert run() == run()


def test_observe_module_has_no_propose_or_signer() -> None:
    import capitalizator.ops.contour as contour_pkg

    assert "strategy_bounce" not in contour_pkg.__dict__
    assert "signer" not in contour_pkg.__dict__
    assert "propose" not in contour_pkg.__dict__


def test_meta_refuses_advice(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    try:
        with pytest.raises(ValueError, match="advise"):
            kn.set_meta("contour", "купи")
        assert kn.meta("contour") is None
    finally:
        kn.close()


def test_unknown_contour_meta_is_error(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.set_meta("contour", "maybe")
    kn.close()
    with pytest.raises(ValueError, match="unknown contour"):
        contour_state(vault)


def test_observe_second_call_is_noop() -> None:
    reg = _reg()
    first = observe(reg, _observe_in(), contour_on=True)
    assert len(first) == 1
    assert observe(reg, _observe_in(), contour_on=True) == []
    assert reg.touches[0].jury == first[0].jury


def test_observe_two_pending_needs_touch_id() -> None:
    """One book must not paint a later print. Two unlabeled rows → error."""
    reg = _reg()
    later = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("101"),
        hi=Decimal("101.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    opened = reg.on_trade(_trade(PRINT + timedelta(seconds=30), px="101.1", qty="4"), [ZONE, later])
    assert len(opened) == 1
    assert len([row for row in reg.touches if row.jury is None]) == 2
    with pytest.raises(ValueError, match="touch_id"):
        observe(reg, _observe_in(), contour_on=True)
    first_id = reg.touches[0].touch_id
    observe(reg, _observe_in(), contour_on=True, touch_id=first_id)
    assert reg.touches[0].jury == "SILENCE"
    assert reg.touches[1].jury is None
    assert reg.touches[1].tape_eaten is None
    assert reg.touches[1].gesture is None


def test_observe_if_on_reads_switch(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    reg = _reg()
    assert observe_if_on(vault, reg, _observe_in()) == []
    assert reg.touches[0].jury is None
    _write_hours24(vault.tape)
    enable(vault)
    changed = observe_if_on(vault, _reg(), _observe_in())
    assert changed[0].jury == "SILENCE"
    assert changed[0].gesture == "DEFEND"


def test_enable_reread_hours24_red_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    _write_hours24(vault.tape)
    calls = {"n": 0}
    real = hours24

    def flaky(events: object, *, symbol: str = "BTCUSDT") -> tuple[bool, float | None]:
        calls["n"] += 1
        if calls["n"] >= 2:
            return False, 86400.0
        return real(events, symbol=symbol)  # type: ignore[arg-type]

    monkeypatch.setattr("capitalizator.ops.contour.hours24", flaky)
    with pytest.raises(ContourNotReady, match="hours24"):
        enable(vault)
    assert contour_state(vault) == "off"
    assert trading_mode() == "off"


def test_observe_refuses_other_symbol_bar() -> None:
    """A BTC book/bar must not stamp an ETH print."""
    eth = Zone.create(
        symbol="ETHUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    reg = Registry(tick_size=TICK)
    opened = reg.on_trade(_trade(PRINT, qty="4"), [eth])
    assert opened == []
    eth_print = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="ETHUSDT",
        exchange_ts=PRINT,
        recv_ts=PRINT,
        seq=None,
        payload={"px": "100.1", "qty": "4", "side": "buy"},
    )
    opened = reg.on_trade(eth_print, [eth])
    assert len(opened) == 1
    with pytest.raises(ValueError, match="not zone"):
        observe(reg, _observe_in(), contour_on=True)
    assert reg.touches[0].jury is None
    assert reg.touches[0].tape_eaten is None
    assert reg.touches[0].cav_label is None


def test_observe_unknown_btc_does_not_freeze_jury() -> None:
    """No BTC label → no jury. A later box fact may still stamp."""
    reg = _reg()
    pending = ObserveIn(
        book=_book(),
        trades=[_trade(PRINT, qty="1", side="sell")],
        adds=[
            BookAdd(
                ts=PRINT + timedelta(seconds=1),
                side="bid",
                px=Decimal("100"),
                qty=Decimal("2"),
            )
        ],
        cav_bar=_bar(),
        htf_bias="unknown",
    )
    first = observe(reg, pending, contour_on=True)
    assert first[0].gesture == "DEFEND"
    assert first[0].cav_label == "REJECT"
    assert first[0].btc_regime is None
    assert first[0].jury is None
    second = observe(reg, _observe_in(), contour_on=True)
    assert second[0].btc_regime == "box"
    assert second[0].jury == "SILENCE"
