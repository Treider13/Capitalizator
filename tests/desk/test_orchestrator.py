"""One-pass orchestrator: fixture tape → touch → ZLG → CAV → jury → shadow → queue."""

from __future__ import annotations

import json
import signal
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.__main__ import main, run_once, stop_on_signals
from capitalizator.desk.loop import DeskLoop
from capitalizator.memory.registry import Touch
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, read_user_mode, set_user_mode
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_trades_100.jsonl"
CREATED = datetime(2024, 8, 29, 12, 0, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("64999"),
    hi=Decimal("65010"),
    method="prior_day_hl",
    created_as_of=CREATED,
)
# A wick through support with a close back inside is a SPRING: traded with the
# zone (buy), stop behind the wick (64998 − 0.8), 2R default target. The old
# reading (short against the held level, tag failed_break_bounce) was inverted.
TARGET = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("64940"),
    hi=Decimal("64950"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


class _VerifiedDesk(DeskLoop):
    """Product send needs a VERIFIED card. Tests stamp it at the live touch."""

    def on_trade(self, trade: MarketEvent, zones: list[Zone]) -> list[dict]:
        out = super().on_trade(trade, zones)
        live = self.state_for(trade.symbol).last_touch
        if live is not None:
            self.registry._patch(
                touch_id=live.touch_id, overwrite=True, bearing_verdict="VERIFIED"
            )
        return out


def _load_trades() -> list[MarketEvent]:
    recv = datetime(2024, 8, 30, 14, 50, tzinfo=UTC)
    lines = FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100
    return [TradesNormalizer().normalize(json.loads(line), recv_ts=recv) for line in lines]


def _book_events(first: MarketEvent) -> list[MarketEvent]:
    """Matching L2 around the 65000 prints. The WS book fixture is 60000 — unusable here."""
    ts = first.exchange_ts
    snap = MarketEvent(
        stream="snapshot",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=1,
        payload={"bids": [["65000.0", "20"]], "asks": [["65000.2", "20"]]},
    )
    add = MarketEvent(
        stream="book_diff",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts + timedelta(milliseconds=100),
        recv_ts=ts + timedelta(milliseconds=100),
        seq=2,
        payload={"bids": [["65000.0", "25"]], "asks": []},
    )
    return [snap, add]


def _wick_and_recover(first: MarketEvent) -> list[MarketEvent]:
    """Wick below the zone, then a print back inside so CAV is REJECT not THROUGH."""
    wick_ts = first.exchange_ts + timedelta(seconds=20)
    recover_ts = first.exchange_ts + timedelta(seconds=21)
    return [
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=wick_ts,
            recv_ts=wick_ts,
            payload={"px": "64998", "qty": "0.001", "side": "sell"},
        ),
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=recover_ts,
            recv_ts=recover_ts,
            payload={"px": "65002", "qty": "0.001", "side": "buy"},
        ),
    ]


def _seed_history(desk: DeskLoop) -> None:
    desk.registry._zones[ZONE.zone_id] = ZONE
    for i in range(20):
        desk.registry.touches.append(
            replace(
                Touch.create(
                    zone_id=ZONE.zone_id,
                    ts=CREATED + timedelta(seconds=i + 1),
                    trade_px=Decimal("65000"),
                    trade_qty=Decimal("1"),
                ),
                outcome="bounce",
                cav_label="REJECT",
                gesture="DEFEND",
                tape_eaten=False,
                btc_regime="box",
            )
        )


def _desk(tmp_path: Path, *, user_mode: str = "demo") -> _VerifiedDesk:
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    if user_mode != "off":
        set_user_mode(vault, user_mode, ack=True)
    knowledge = open_knowledge(vault)
    desk = _VerifiedDesk(
        knowledge=knowledge,
        user_mode=read_user_mode(vault),
        tick_size=TICK,
    )
    _seed_history(desk)
    return desk


def test_play_100_trades_runs_full_chain(tmp_path: Path) -> None:
    trades = _load_trades()
    events = [*_book_events(trades[0]), *trades, *_wick_and_recover(trades[0])]
    now = datetime(2024, 8, 30, 15, 0, tzinfo=UTC)
    desk = _desk(tmp_path, user_mode="demo")
    out = desk.play(events, extra_zones=(ZONE, TARGET), now=now)

    live = [t for t in desk.registry.touches if t.ts >= trades[0].exchange_ts]
    assert live, "orchestrator must open a touch from the 100-print fixture"
    row = live[-1]
    assert row.gesture is not None
    assert row.cav_label is not None
    assert row.jury is not None

    kinds = {e.get("event") for e in out}
    assert "armed" in kinds
    assert "zlg" in kinds
    assert "jury" in kinds

    journal = desk.knowledge.get_journal_touch(row.touch_id)
    assert journal is not None
    assert journal["zlg_label"] == row.gesture
    assert journal["cav_label"] == row.cav_label
    assert journal["jury"] == row.jury
    assert desk.shadow_writes
    assert desk.shadow_writes[-1]["mode"] == "shadow"
    assert desk.shadow_writes[-1]["sent"] is False
    assert desk.shadow_writes[-1]["payload"]["touch_id"] == row.touch_id

    jury_ev = next(e for e in out if e.get("event") == "jury")
    # No branching on the result: the fixture MUST reach ACCORD.
    assert journal["jury"] == "ACCORD"
    assert journal["shadow_would"] is True
    assert journal["shadow_side"] == "buy"
    assert journal["shadow_tag"] == "spring"
    assert journal["idea_side"] == "buy"
    assert journal["fade_side"] == "sell"
    assert journal["fade_tag"] == "fade_spring"
    assert journal["wick_extreme"] == "64998"
    assert row.idea == "spring"
    assert row.shadow_would is True
    assert row.shadow_side == "buy"
    # D-06: an 11-tick zone on BTC gives R = 2.8 USDT/coin; the maker round trip on
    # the sized position is ~9x that. The EV gate refuses and says so in the journal.
    assert jury_ev["sent"] is False
    assert journal["send_skip"] == "ev:fee_gt_r"
    assert journal["sizing"]["action"] == "accept"
    assert Decimal(journal["sizing"]["qty"]) > 0
    assert journal["ev"]["ok"] is False
    assert Decimal(journal["ev"]["r_net_3r"]) < 0  # even a 3R win would lose money
    assert desk.knowledge.pending_intents() == []
    assert desk.account.open == {}


def test_play_sends_when_r_covers_fees(tmp_path: Path) -> None:
    """Same fixture, a zone wide enough that 1R ≥ fee_multiple_min × costs → sized intent."""
    trades = _load_trades()
    events = [*_book_events(trades[0]), *trades, *_wick_and_recover(trades[0])]
    now = datetime(2024, 8, 30, 15, 0, tzinfo=UTC)
    wide = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("64300"),
        hi=Decimal("65010"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    desk = _desk(tmp_path, user_mode="demo")
    desk.registry._zones[wide.zone_id] = wide
    for touch in list(desk.registry.touches):
        desk.registry.touches.remove(touch)
        desk.registry.touches.append(replace(touch, zone_id=wide.zone_id))
    out = desk.play(events, extra_zones=(wide,), now=now)
    jury_ev = next(e for e in out if e.get("event") == "jury")
    journal = desk.knowledge.get_journal_touch(jury_ev["touch_id"])
    assert journal["jury"] == "ACCORD"
    assert jury_ev["sent"] is True, journal.get("send_skip")
    pending = desk.knowledge.pending_intents()
    assert len(pending) == 1
    payload = pending[0]["payload"]
    assert payload["side"] == "buy" and payload["tag"] == "bounce"  # wick stays inside the wide zone
    # structural = band stop 64299.2 (further than the wick stop); hybrid mode adds
    # max(k·ATR, 3·spread, tick) below it — the book spread here is 0.2 → 0.6.
    assert Decimal(payload["structural"]) == Decimal("64299.2")
    assert Decimal(payload["stop"]) == Decimal("64298.6")
    assert payload["stop_components"]["mode"] == "hybrid"
    assert Decimal(payload["stop_components"]["buffer"]) == Decimal("0.6")
    assert Decimal(payload["tp"]) == Decimal("65000") + 2 * (Decimal("65000") - Decimal("64298.6"))
    assert Decimal(payload["qty"]) > 0 and payload["size_mult"] == "1"
    assert payload["lev"] == "3" and payload["risk_config_id"] == desk.risk_config.config_id
    assert payload["valid_until"] is not None
    # sizing law 8: margin ≤ 10% equity (deposit_share binding), risk ≤ 1%
    sizing = journal["sizing"]
    assert sizing["binding"] == "deposit_share"
    assert Decimal(sizing["margin"]) <= Decimal("10000")
    assert Decimal(sizing["risk_frac"]) <= Decimal("0.01")
    ev = journal["ev"]
    assert ev["ok"] is True and Decimal(ev["fee_multiple"]) >= 5
    assert Decimal(ev["r_net_1r"]) > 0
    # the account now carries the open idea; a second entry on BTC is refused
    assert "BTCUSDT" in desk.account.open
    assert desk.account.allow_entry("BTCUSDT") == (False, "position_open_same_symbol")
    assert desk.risk.allow_entry("BTCUSDT") is False
    row = next(t for t in desk.registry.touches if t.touch_id == jury_ev["touch_id"])
    assert row.session_hour is not None
    assert row.n_cav == journal["n_cav"]
    assert row.n_zlg == journal["n_zlg"]
    assert row.card_id == journal["card_id"]
    assert row.first_fact == journal["first_fact"]
    assert row.cav_tf == "15m"


def test_play_off_mode_writes_shadow_not_intent(tmp_path: Path) -> None:
    trades = _load_trades()
    events = [*_book_events(trades[0]), *trades, *_wick_and_recover(trades[0])]
    now = datetime(2024, 8, 30, 15, 0, tzinfo=UTC)
    desk = _desk(tmp_path, user_mode="off")
    out = desk.play(events, extra_zones=(ZONE,), now=now)
    assert desk.shadow_writes
    jury = next(e for e in out if e.get("event") == "jury")
    assert jury["sent"] is False
    assert desk.knowledge.pending_intents() == []


def test_run_once_reads_parquet_tape(tmp_path: Path) -> None:
    trades = _load_trades()
    vault = init_vault(tmp_path / "once")
    sink = ParquetSink(vault.tape)
    for event in [*_book_events(trades[0]), trades[0]]:
        sink.write(event)
    knowledge = open_knowledge(vault)
    desk = run_once(
        vault=vault,
        knowledge=knowledge,
        now=trades[0].exchange_ts + timedelta(seconds=8),
        extra_zones=(ZONE,),
    )
    st = desk.state_for("BTCUSDT")
    assert st.trades
    assert st.state in {"LABEL_ZLG", "IDLE", "JURY"}
    assert st.state != "ARM_ZLG"
    knowledge.close()


def test_play_late_now_labels_zlg_before_jury(tmp_path: Path) -> None:
    """`--once` catch-up: now is hours later. Tick ZLG before the closed-bar jury."""
    trades = _load_trades()
    events = [*_book_events(trades[0]), trades[0]]
    late = trades[0].exchange_ts + timedelta(hours=2)
    desk = _desk(tmp_path, user_mode="off")
    out = desk.play(events, extra_zones=(ZONE,), now=late)
    kinds = [e.get("event") for e in out]
    assert kinds.index("zlg") < kinds.index("jury")
    live = [t for t in desk.registry.touches if t.ts >= trades[0].exchange_ts]
    assert live
    assert live[-1].gesture is not None
    journal = desk.knowledge.get_journal_touch(live[-1].touch_id)
    assert journal is not None
    assert journal["zlg_label"] is not None


def test_main_once_walks_empty_tape(tmp_path: Path) -> None:
    root = tmp_path / "cli"
    assert main(["--userdir", str(root), "--init", "--once"]) == 0


def test_stop_on_signals_flips_on_sigterm() -> None:
    prev_int = signal.getsignal(signal.SIGINT)
    prev_term = signal.getsignal(signal.SIGTERM)
    try:
        should_stop = stop_on_signals()
        assert should_stop() is False
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        assert should_stop() is True
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
