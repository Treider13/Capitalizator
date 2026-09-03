"""Э4: wake-on-event. Sleep is an idle deadline, not the decision path."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.desk.__main__ import serve_loop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, set_user_mode
from capitalizator.ops.vault import init_vault
from capitalizator.ops.wake import StampWake, Wake, desk_wake, idle, signer_wake
from capitalizator.recorder.sink_parquet import BufferedParquetSink, ParquetSink
from capitalizator.signer.process import serve_loop as signer_serve
from capitalizator.types import MarketEvent

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
INTENT = {
    "symbol": "BTCUSDT",
    "side": "buy",
    "qty": "0.001",
    "limit_px": "100",
    "stop_px": "99",
    "tp_px": "102",
    "reduce_only_stop": True,
}


def _trade() -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=NOW,
        recv_ts=NOW,
        payload={"px": "100.4", "qty": "1", "side": "sell"},
    )


def test_in_process_wake_is_immediate() -> None:
    wake = Wake()
    assert wake.wait(0) is False
    t0 = time.monotonic()
    threading.Timer(0.02, wake.notify).start()
    assert wake.wait(1.0) is True
    assert time.monotonic() - t0 < 0.5


def test_stamp_wake_sees_other_instance(tmp_path: Path) -> None:
    path = tmp_path / "wake" / "desk.stamp"
    a = StampWake(path)
    b = StampWake(path)
    assert a.wait(0) is False
    b.notify()
    assert a.wait(0.2) is True
    assert path.is_file()
    assert path.stat().st_nlink == 1


def test_idle_returns_on_notify_before_deadline() -> None:
    wake = Wake()
    t0 = time.monotonic()
    threading.Timer(0.02, wake.notify).start()
    assert idle(wake, 2.0) is True
    assert time.monotonic() - t0 < 0.5


def test_enqueue_intent_oms_command_touch_signer_stamp(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    stamp = vault.root / "wake" / "signer.stamp"
    assert stamp.exists()
    before = stamp.stat().st_mtime_ns
    kn.enqueue_intent(INTENT, created_ts=NOW.isoformat())
    assert stamp.stat().st_mtime_ns != before
    before = stamp.stat().st_mtime_ns
    kn.enqueue_oms(
        kind="flatten",
        symbol="BTCUSDT",
        payload={"reason": "test"},
        created_ts=NOW.isoformat(),
    )
    assert stamp.stat().st_mtime_ns != before
    before = stamp.stat().st_mtime_ns
    kn.enqueue_command("pause_entries", {"reason": "test"}, created_ts=NOW.isoformat())
    assert stamp.stat().st_mtime_ns != before
    kn.close()


def test_parquet_write_notifies_desk_wake(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    wake = desk_wake(vault)
    assert wake.wait(0) is False
    ParquetSink(vault.tape, on_write=wake.notify).write(_trade())
    assert wake.wait(0.2) is True


def test_live_jsonl_write_notifies_desk_wake(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    wake = desk_wake(vault)
    sink = BufferedParquetSink(
        vault.tape, flush_every_s=60, max_rows=10_000, live_jsonl=True, on_write=wake.notify
    )
    sink.write(_trade())
    assert wake.wait(0.2) is True
    sink.close()


def test_desk_serve_wakes_on_parquet_without_full_idle(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    wake = desk_wake(vault)
    seen: list[int] = []

    def should_stop() -> bool:
        return len(seen) >= 2

    def on_tick(_desk: object) -> None:
        seen.append(len(seen) + 1)
        if len(seen) == 1:
            ParquetSink(vault.tape, on_write=wake.notify).write(_trade())

    t0 = time.monotonic()
    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=should_stop,
        idle_s=5.0,
        wake=wake,
        on_tick=on_tick,
        now=NOW,
    )
    knowledge.close()
    assert time.monotonic() - t0 < 1.5
    assert len(seen) >= 2
    assert desk.state_for("BTCUSDT").trades


def test_signer_serve_wakes_on_enqueue_without_full_idle(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    knowledge = open_knowledge(vault)
    wake = signer_wake(vault)
    stop = {"v": False}
    started = threading.Event()

    def should_stop() -> bool:
        return stop["v"]

    def run() -> None:
        def _stop() -> bool:
            if knowledge.meta("signer_heartbeat"):
                started.set()
            return should_stop()

        signer_serve(
            knowledge=knowledge,
            vault=vault,
            should_stop=_stop,
            idle_s=5.0,
            now=NOW,
            wake=wake,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(2.0)
    knowledge.enqueue_intent(INTENT, created_ts=NOW.isoformat())
    deadline = time.monotonic() + 2.0
    while knowledge.pending_intents() and time.monotonic() < deadline:
        time.sleep(0.01)
    pending = knowledge.pending_intents()
    parked = knowledge.intents_with_status("no_gateway")
    stop["v"] = True
    wake.notify()
    thread.join(2.0)
    knowledge.close()
    assert pending == []
    assert len(parked) == 1
