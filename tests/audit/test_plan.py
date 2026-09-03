"""Audit locks vs the product plan. Fail closed on missing §5.3 / desk / send."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.desk.loop import DeskLoop
from capitalizator.jury.desk import decide, voices_for_bounce
from capitalizator.memory.journal import JOURNAL_KEYS, KNOWLEDGE_TABLES
from capitalizator.memory.registry import Registry, Touch
from capitalizator.ops.console import ConsoleApp, _handler, desk_snapshot
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.screener.universe import load_desk_universe
from capitalizator.signer.process import (
    HEARTBEAT_S,
    RECONCILE_S,
    on_signer_exit,
    unsigned_from_intent,
    validate_queue_payload,
)
from capitalizator.signer.validate import Signer, UnsignedIntent
from capitalizator.types import MarketEvent
from capitalizator.zlg.gesture import ZLG, BookAdd
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
WINDOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _trade(ts: datetime = WINDOW, *, px: str = "100.4") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "1", "side": "sell"},
    )


def _book() -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            seq=1,
            bids=(("100.4", "20"),),
            asks=(("100.6", "20"),),
        )
    )
    return book


def _bar(
    ts: datetime,
    *,
    low: str = "100.2",
    high: str = "101",
    close: str = "100.6",
) -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=ts - timedelta(minutes=15),
        close_ts=ts,
        open=Decimal("100.5"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def _desk(tmp_path: Path, *, user_mode: str = "off") -> DeskLoop:
    return DeskLoop(
        knowledge=open_knowledge(init_vault(tmp_path / "desk")),
        user_mode=user_mode,
        tick_size=TICK,
    )


def test_schema_has_plan_tables(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    names = knowledge.table_names()
    missing = set(KNOWLEDGE_TABLES) - names
    assert missing == set()


def test_journal_row_has_all_5_3_keys(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_event({"kind": "bar_close", "bar": _bar(WINDOW + timedelta(minutes=15))})
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    missing = [key for key in JOURNAL_KEYS if key not in row]
    assert missing == []


def test_on_event_covers_plan_streams(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    kinds = []
    for stream in ("funding", "oi", "mark", "bbo", "book_diff", "gap", "resync"):
        ev = MarketEvent(
            stream=stream,  # type: ignore[arg-type]
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=WINDOW,
            recv_ts=WINDOW,
            payload={},
        )
        out = desk.on_event(ev)
        kinds.append(out[0]["event"])
    assert "funding" in kinds
    assert "gap" in kinds
    assert desk.on_event({"kind": "mode_change", "user_mode": "learn"})[0]["user_mode"] == "learn"
    assert desk.on_event({"kind": "flatten", "symbol": "BTCUSDT"})[0]["event"] == "flatten"


def test_stamp_jury_honors_wall_and_btc_and_card() -> None:
    reg = Registry(tick_size=TICK)
    opened = reg.on_trade(_trade(), [ZONE])
    tid = opened[0].touch_id
    reg.fill_cav(cav_label="REJECT", touch_id=tid)
    reg.fill_gesture(gesture="DEFEND", touch_id=tid)
    reg.fill_btc(regime="box", touch_id=tid)
    veto = reg.stamp_jury(
        n_cav=20,
        n_zlg=20,
        touch_id=tid,
        btc_break_against=True,
    )
    assert veto[0].jury == "VETO"
    reg2 = Registry(tick_size=TICK)
    opened = reg2.on_trade(_trade(WINDOW + timedelta(seconds=1)), [ZONE])
    tid = opened[0].touch_id
    reg2.fill_cav(cav_label="REJECT", touch_id=tid)
    reg2.fill_gesture(gesture="DEFEND", touch_id=tid)
    reg2.fill_btc(regime="box", touch_id=tid)
    card = reg2.stamp_jury(
        n_cav=20,
        n_zlg=20,
        touch_id=tid,
        card_bearing_verdict="REFUTED",
    )
    assert card[0].jury == "VETO"


def test_silence_zlg_is_veto_not_accord() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="SILENCE",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
    )
    assert decide(voices) == "VETO"


def test_dirty_book_is_zlg_silence() -> None:
    touch = Touch.create(
        zone_id="z", ts=WINDOW, trade_px=Decimal("100.4"), trade_qty=Decimal("4")
    )
    got = ZLG(tick_size=TICK).classify(
        touch,
        [
            BookAdd(
                ts=WINDOW + timedelta(seconds=1),
                side="bid",
                px=Decimal("100.4"),
                qty=Decimal("2"),
            )
        ],
        Decimal("4"),
        hit_side="bid",
        mid=Decimal("100.5"),
        opp_best=Decimal("100.6"),
        book_ready=False,
    )
    assert got.gesture == "SILENCE"


def test_fill_tape_accepts_book_pre_kw() -> None:
    reg = Registry(tick_size=TICK)
    opened = reg.on_trade(_trade(), [ZONE])
    changed = reg.fill_tape(book_pre=_book(), trades=[_trade()], touch_id=opened[0].touch_id)
    assert changed[0].tape_eaten is False


def test_demo_send_requires_hello(tmp_path: Path) -> None:
    desk = _desk(tmp_path, user_mode="demo")
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    assert events[0]["sent"] is False
    assert desk.knowledge.pending_intents() == []


def test_console_demo_without_hello_is_403(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/mode",
            body='{"mode":"demo","ack_token":true}',
            headers={"Content-Type": "application/json"},
        )
        assert conn.getresponse().status == 403
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_console_snapshot_lists_24_symbols(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    snap = desk_snapshot(vault)
    assert snap["n_symbols"] == 24
    assert snap["symbols"][0] == "BTCUSDT"
    assert "Демо: нет hello" in snap["hello_banner"]
    assert "мало n" in snap["hello_banner"]


def test_signer_requires_reduce_only_stop() -> None:
    raw = UnsignedIntent(
        symbol="BTCUSDT",
        side="buy",
        qty=Decimal("0.001"),
        limit_px=Decimal("60000"),
        stop_px=Decimal("59400"),
        tp_px=Decimal("61200"),
        trading_mode="testnet",
    )
    order = Signer().validate(raw)
    assert order.reduce_only_stop is True
    assert order.tp_px == Decimal("61200")
    with pytest.raises(ValueError, match="reduce-only"):
        Signer().validate(raw.model_copy(update={"reduce_only_stop": False}))


def test_signer_exit_calls_cancel_all() -> None:
    hits: list[int] = []
    on_signer_exit(lambda: hits.append(1))
    assert hits == [1]


def test_two_parquet_writers_do_not_corrupt(tmp_path: Path) -> None:
    sink_a = ParquetSink(tmp_path)
    sink_b = ParquetSink(tmp_path)
    errors: list[BaseException] = []

    def write(sink: ParquetSink, n: int) -> None:
        try:
            for i in range(5):
                sink.write(
                    MarketEvent(
                        stream="trades",
                        exchange="bybit",
                        symbol="BTCUSDT",
                        exchange_ts=WINDOW + timedelta(milliseconds=n * 10 + i),
                        recv_ts=WINDOW + timedelta(milliseconds=n * 10 + i),
                        payload={"px": "1", "qty": "0.001", "side": "buy"},
                    )
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=write, args=(sink_a, 1))
    t2 = threading.Thread(target=write, args=(sink_b, 2))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == []
    assert sink_a.accepted_count + sink_b.accepted_count == 10


def test_btc_same_side_is_plus_one_not_zero() -> None:
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="long",
        btc_same_side=True,
    )
    assert voices.btc == 1


def test_console_html_has_plan_screen(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    from capitalizator.ops.console import render_html

    page = render_html(vault)
    assert "BTCUSDT" in page
    assert "SOLUSDT" in page
    assert "CAV × ZLG × outcome" in page
    assert "Жюри дня" in page
    assert "n касаний" in page
    assert "День учёбы" in page
    assert "Дыры ленты" in page
    assert "тень" in page and "демо" in page and "лайв" in page
    assert "Краны" in page
    assert "dead_man_s: 30" in page
    assert "reconcile_s: 60" in page
    assert "first_minute_s: 60" in page
    assert "max_lev: 3" in page
    assert "target_risk: 0.01" in page
    snap = desk_snapshot(vault)
    assert snap["n_symbols"] == 24
    assert "tape_holes" in snap
    assert "cav_zlg" in snap
    assert "jury_today" in snap
    assert "shadow_vs_demo_vs_live" in snap
    assert snap["taps"] == {
        "dead_man_s": 30,
        "reconcile_s": 60,
        "first_minute_s": 60,
        "max_lev": 3,
        "target_risk": 0.01,
    }


def test_desk_and_signer_are_separate_processes(tmp_path: Path) -> None:
    import capitalizator.desk.__main__ as desk_main
    import capitalizator.signer.__main__ as signer_main

    assert "signer" not in desk_main.__dict__
    assert HEARTBEAT_S == 30
    assert RECONCILE_S == 60
    vault_dir = str(tmp_path / "desk")
    assert desk_main.main(["--userdir", vault_dir, "--init", "--once"]) == 0
    assert signer_main.main(["--userdir", vault_dir, "--once"]) == 0


def test_desk_serve_loop_refreshes_mode_from_sqlite(tmp_path: Path) -> None:
    """§2: desk --serve stays up and re-reads user_mode (console writes SQLite)."""
    from capitalizator.desk.__main__ import serve_loop
    from capitalizator.ops.product import set_user_mode

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    seen: list[str] = []
    n = {"i": 0}

    def should_stop() -> bool:
        n["i"] += 1
        if n["i"] == 2:
            set_user_mode(vault, "learn", ack=True, learn_n_days=1)
        return n["i"] >= 3

    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=should_stop,
        idle_s=0,
        on_tick=lambda d: seen.append(d.user_mode),
    )
    knowledge.close()
    assert n["i"] >= 3
    assert "learn" in seen
    assert desk.user_mode == "learn"


def test_signer_serve_loop_drains_queue(tmp_path: Path) -> None:
    """§2: signer --serve drains intent_queue and beats dead-man."""
    from capitalizator.ops.product import mark_hello, set_user_mode
    from capitalizator.signer.process import serve_loop

    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    knowledge = open_knowledge(vault)
    knowledge.enqueue_intent(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "qty": "0.001",
            "limit_px": "100",
            "stop_px": "99",
            "tp_px": "102",
            "reduce_only_stop": True,
        },
        created_ts=WINDOW.isoformat(),
    )
    sent: list[dict] = []
    n = {"i": 0}

    def should_stop() -> bool:
        n["i"] += 1
        return n["i"] >= 2

    serve_loop(
        knowledge=knowledge,
        vault=vault,
        send=lambda row: sent.append(row) or {"status": "sent"},
        cancel_all=lambda: None,
        should_stop=should_stop,
        idle_s=0,
        now=WINDOW,
    )
    knowledge.close()
    assert sent
    assert sent[0]["symbol"] == "BTCUSDT"


def test_desk_screener_accepts_sol(tmp_path: Path) -> None:
    from capitalizator.exec.strategy_bounce import BounceStrategy
    from capitalizator.risk.halts import Halts
    from capitalizator.risk.schema import RiskEngine

    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    assert "SOLUSDT" in strat.screener.universe.symbols
    assert len(load_desk_universe().symbols) == 24
    desk_strat = DeskLoop(
        knowledge=open_knowledge(init_vault(tmp_path / "desk")),
        user_mode="demo",
    ).strategy
    assert "SOLUSDT" in desk_strat.screener.universe.symbols


def test_signer_desk_universe_accepts_sol() -> None:
    raw = unsigned_from_intent(
        {
            "symbol": "SOLUSDT",
            "side": "buy",
            "qty": "1",
            "entry": "100",
            "stop": "99",
            "tp": "102",
        }
    )
    assert raw.symbol == "SOLUSDT"
    order = validate_queue_payload(
        {
            "symbol": "SOLUSDT",
            "side": "buy",
            "qty": "1",
            "entry": "100",
            "stop": "99",
            "tp": "102",
        }
    )
    assert order["reduce_only_stop"] is True
    assert Decimal(str(order["stop_px"])) == Decimal("99")


def test_signer_payload_without_stop_is_error() -> None:
    with pytest.raises(ValueError, match="stop"):
        unsigned_from_intent({"symbol": "BTCUSDT", "side": "buy", "entry": "100"})


def test_flatten_resets_symbol_state(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    assert desk.state_for("BTCUSDT").state == "ARM_ZLG"
    out = desk.on_event({"kind": "flatten", "symbol": "BTCUSDT"})
    assert out[0]["event"] == "flatten"
    assert out[0]["state"] == "IDLE"
    assert desk.state_for("BTCUSDT").state == "IDLE"
    assert desk.state_for("BTCUSDT").last_touch is None
    assert out[0]["action"] == "flatten"


def test_organism_replay_twice_same_labels(tmp_path: Path) -> None:
    def run(root: Path) -> dict:
        desk = _desk(root)
        desk.on_book("BTCUSDT", _book())
        desk.on_event(_trade(), [ZONE])
        desk.tick(WINDOW + timedelta(seconds=8))
        events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
        row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
        assert row is not None
        return {
            "zone_id": row["zone_id"],
            "zlg": row["zlg_label"],
            "cav": row["cav_label"],
            "jury": row["jury"],
            "shadow_would": row["shadow_would"],
        }

    assert run(tmp_path / "a") == run(tmp_path / "b")


def test_demo_hello_sends_stop_in_payload(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    desk = DeskLoop(knowledge=open_knowledge(vault), user_mode="demo", tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    from dataclasses import replace

    from capitalizator.memory.registry import Touch

    for i in range(20):
        desk.registry.touches.append(
            replace(
                Touch.create(
                    zone_id=ZONE.zone_id,
                    ts=CREATED + timedelta(seconds=i + 1),
                    trade_px=Decimal("100.5"),
                    trade_qty=Decimal("1"),
                ),
                outcome="bounce",
                cav_label="REJECT",
                gesture="DEFEND",
                tape_eaten=False,
                btc_regime="box",
            )
        )
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    live = desk.state_for("BTCUSDT").last_touch
    assert live is not None
    desk.registry._patch(
        touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED"
    )
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    if row["jury"] == "ACCORD":
        assert events[0]["sent"] is True
        pending = desk.knowledge.pending_intents()
        assert pending
        assert pending[0]["payload"].get("stop") is not None
    else:
        assert events[0]["sent"] is False


def test_demo_without_verified_card_does_not_send() -> None:
    from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
    from capitalizator.risk.halts import Halts
    from capitalizator.risk.schema import RiskEngine

    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    snap = BounceSnapshot(
        now=WINDOW,
        symbol="BTCUSDT",
        price=Decimal("100.5"),
        tick=TICK,
        trading_mode="demo",
        zone=ZONE,
        zones=(ZONE,),
        spread_frac=Decimal("0.001"),
        typical_move=Decimal("0.01"),
        idea="bounce",
        jury="ACCORD",
        cav_label="REJECT",
        zlg_label="DEFEND",
        n_cav=20,
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        gesture_n=20,
        card_bearing_verdict=None,
    )
    assert strat.propose(snap) is None
    assert strat.propose(
        BounceSnapshot(**{**snap.__dict__, "card_bearing_verdict": "VERIFIED"})
    ) is not None


def test_screener_rejects_delist_funding_volume() -> None:
    from capitalizator.screener.filters import Screener

    scr = Screener()
    assert (
        scr.ok("BTCUSDT", spread_frac=Decimal("0.001"), typical_move=Decimal("0.01"))
        is True
    )
    assert (
        scr.ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            delisted=True,
        )
        is False
    )
    assert (
        scr.ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            funding_extreme=True,
        )
        is False
    )
    assert (
        scr.ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            volume_ok=False,
        )
        is False
    )


def test_nmin_size_stays_zero() -> None:
    from capitalizator.risk.nmin import NMIN_SIZE

    assert NMIN_SIZE == Decimal("0")


def test_f5_1_2_needs_ack() -> None:
    from capitalizator.risk.f5 import F1_TARGET, F5_TARGET, active_target, f5_target

    assert f5_target(equity_source="main", gate_f4=True, ack=False) is None
    assert f5_target(equity_source="main", gate_f4=True, ack=True) == F5_TARGET
    assert active_target(equity_source="main", gate_f4=True, ack=False) == F1_TARGET


def test_desk_cav_on_closed_reject_bar_is_not_noise(tmp_path: Path) -> None:
    """§3/§6.5: t=close_ts made every live CAV NOISE. Closed reject bar must label REJECT."""
    desk = _desk(tmp_path)
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(
        _bar(WINDOW + timedelta(minutes=15), low="99.9", close="100.4")
    )
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["cav_label"] == "REJECT"
    assert row["bar_quality"] in {"live", "stagnant", "illiquid"}
    assert row["symbol"] == "BTCUSDT"
    assert row["card_id"]
    assert "BTCUSDT" in desk.last_price
    assert desk.knowledge.last_prices()["BTCUSDT"] == str(desk.last_price["BTCUSDT"])
    assert desk.knowledge.list_zones(symbol="BTCUSDT")
    assert desk.knowledge.list_claims(card_id=str(row["card_id"]))


def test_desk_d1_against_is_cav_noise(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    day0 = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
    for i, close in enumerate(("110", "111", "70")):
        desk.state_for("BTCUSDT").bars.append(
            Bar(
                symbol="BTCUSDT",
                tf="1d",
                open_ts=day0 + timedelta(days=i),
                close_ts=day0 + timedelta(days=i, hours=23),
                open=Decimal("100"),
                high=Decimal("120"),
                low=Decimal("100") if i < 2 else Decimal("60"),
                close=Decimal(close),
            )
        )
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15), low="99.9", close="100.4"))
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["cav_label"] == "NOISE"
    assert row["htf_d1"] == "short"


def test_desk_mid_band_is_not_cav(tmp_path: Path) -> None:
    resist = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("102"),
        hi=Decimal("103"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    desk = _desk(tmp_path)
    desk.registry._zones[ZONE.zone_id] = ZONE
    desk.registry._zones[resist.zone_id] = resist
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(px="100.4"), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    mid_bar = _bar(WINDOW + timedelta(minutes=15), low="100.2", high="102", close="101.5")
    events = desk.on_bar_close(mid_bar)
    if not events:
        return
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert row["cav_label"] == "NOISE"


def test_desk_writes_imbalance_journal_not_entry(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.on_book("BTCUSDT", _book())
    desk.on_event(_trade(), [ZONE])
    desk.tick(WINDOW + timedelta(seconds=8))
    events = desk.on_bar_close(_bar(WINDOW + timedelta(minutes=15)))
    row = desk.knowledge.get_journal_touch(events[0]["touch_id"])
    assert row is not None
    assert "imbalance" in row
    assert desk.knowledge.pending_intents() == []


def test_recorder_is_runnable_as_process() -> None:
    """§2: python -m capitalizator.recorder (healthz, no key)."""
    import json
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "capitalizator.recorder"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["healthz"] == 200


def test_ticker_emits_mark_with_funding_and_oi() -> None:
    """§6.1: funding / OI / mark from the same public ticker frame."""
    from capitalizator.recorder.live import ticker_events

    events = ticker_events(
        {
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "fundingRate": "0.0001",
                "openInterest": "12",
                "markPrice": "65000.1",
                "ts": 1725024600000,
            },
        },
        recv_ts=WINDOW,
    )
    streams = {e.stream for e in events}
    assert streams == {"funding", "oi", "mark"}
    mark = next(e for e in events if e.stream == "mark")
    assert mark.payload["mark"] == "65000.1"


def test_minutes_cli_announces_24_symbol_subscribe(tmp_path: Path, capsys) -> None:
    """§2 / wave 2: --minutes without jsonl is live; subscribe covers 24 symbols."""
    import json

    from capitalizator.recorder.app import main

    assert main(["--minutes", "1", "--data-root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["live"] is True
    assert payload["n_symbols"] == 24
    assert payload["subscribe"]["op"] == "subscribe"
    assert len(payload["subscribe"]["args"]) == 24 * 5  # + allLiquidation (ОКО След)


def test_rest_ticker_is_funding_oi_mark() -> None:
    """§6.1 REST half: same three streams as the public ticker WS."""
    from capitalizator.recorder.rest_ticker import RestTicker

    events = RestTicker().parse(
        {
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "symbol": "ETHUSDT",
                        "fundingRate": "0.01",
                        "openInterest": "3",
                        "markPrice": "3000",
                    }
                ]
            },
        },
        recv_ts=WINDOW,
    )
    assert {e.stream for e in events} == {"funding", "oi", "mark"}


def test_ptf_pickable_only_n20_and_real() -> None:
    from capitalizator.champion.ptf import ClassStat, PtfTable

    stat20 = ClassStat(
        class_id="bounce × REJECT × DEFEND × BTC_box",
        n=20,
        avg_r=Decimal("0.5"),
        hours=Decimal("3"),
    )
    assert PtfTable().evaluate(stat20).pickable is False
    assert PtfTable().evaluate(stat20, in_real=True).pickable is True
    stat19 = ClassStat(
        class_id=stat20.class_id,
        n=19,
        avg_r=Decimal("0.5"),
        hours=Decimal("3"),
    )
    assert PtfTable().evaluate(stat19, in_real=True).pickable is False
    stat139 = ClassStat(
        class_id=stat20.class_id,
        n=139,
        avg_r=Decimal("0.5"),
        hours=Decimal("3"),
    )
    assert PtfTable().evaluate(stat139).pickable is False
