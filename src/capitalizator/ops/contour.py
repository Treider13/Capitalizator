"""F0 contour switch. After 24h tape, a human may turn recording on.

On: one observe() fills tape + CAV + ZLG + BTC + jury on a touch.
Does not write infra/phase.yaml. Does not open size. Does not send orders.
hours24 uses check_uptime --hours 24 --max-unmarked-gap-s 0 (PHASE-BUILD 0.1.7).
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

import pyarrow.parquet as pq

from capitalizator.book.reconstruct import Book
from capitalizator.btc.regime import BtcRegime
from capitalizator.card.live import CardLive, card_is_fresh
from capitalizator.memory.registry import Registry, Touch
from capitalizator.ops.check_uptime import check_uptime, parse_event_row
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.phase import trading_mode
from capitalizator.ops.vault import Vault, iter_regular_files, open_regular
from capitalizator.patterns.cav import label as cav_label
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zlg.gesture import ZLG, BookAdd
from capitalizator.zones.map import HtfBias
from capitalizator.zones.model import Bar

ContourState = Literal["off", "on"]
HOURS24 = 24.0
MAX_UNMARKED_GAP_S = 0.0
META_KEY = "contour"


class ContourNotReady(ValueError):
    """hours24 is red, or knowledge db is missing. Contour stays off."""


@dataclass(frozen=True)
class ObserveIn:
    book: Book
    trades: Sequence[MarketEvent]
    adds: Sequence[BookAdd]
    cav_bar: Bar
    htf_bias: HtfBias
    closed_bars: Sequence[Bar] = field(default_factory=tuple)
    btc_bars: Sequence[Bar] = field(default_factory=tuple)
    news_known_at: datetime | None = None
    card: CardLive | None = None


def load_tape_events(vault: Vault, *, symbol: str) -> list[MarketEvent]:
    """Read parquet via regular files only. rglob can follow a tapedir symlink."""
    events: list[MarketEvent] = []
    if vault.tape.is_symlink():
        raise ValueError(f"symlink: {vault.tape}")
    if not vault.tape.is_dir():
        return events
    for path in iter_regular_files(vault.tape):
        if path.suffix != ".parquet":
            continue
        if symbol not in path.parts:
            continue
        fd = open_regular(path)
        fh = os.fdopen(fd, "rb")
        try:
            table = pq.ParquetFile(fh).read()
        except (OSError, ValueError):
            continue
        finally:
            fh.close()
        for row in table.to_pylist():
            if row.get("symbol") != symbol:
                continue
            event = parse_event_row(row)
            if event is not None:
                events.append(event)
    return events


def hours24(
    events: Sequence[MarketEvent],
    *,
    symbol: str = "BTCUSDT",
) -> tuple[bool, float | None]:
    """Same law as check_uptime --hours 24 --max-unmarked-gap-s 0."""
    trades = [e for e in events if e.stream == "trades" and e.symbol == symbol]
    trades = sorted(trades, key=lambda e: e.exchange_ts)
    span: float | None = None
    if len(trades) >= 2:
        span = (trades[-1].exchange_ts - trades[0].exchange_ts).total_seconds()
    try:
        check_uptime(
            list(events),
            hours=HOURS24,
            max_unmarked_gap_s=MAX_UNMARKED_GAP_S,
            symbol=symbol,
        )
    except SystemExit:
        return False, span
    return True, span


def contour_state(vault: Vault) -> ContourState:
    knowledge = open_knowledge(vault, create=False)
    try:
        raw = knowledge.meta(META_KEY)
    finally:
        knowledge.close()
    if raw is None or raw == "off":
        return "off"
    if raw == "on":
        return "on"
    raise ValueError(f"unknown contour: {raw!r}")


def status(vault: Vault, *, symbol: str = "BTCUSDT") -> dict[str, Any]:
    events = load_tape_events(vault, symbol=symbol)
    ok, span = hours24(events, symbol=symbol)
    state = contour_state(vault)
    snap = {
        "contour": state,
        "hours24": ok,
        "hours24_span_s": span,
        "trading_mode": trading_mode(),
        "can_enable": ok and state == "off",
    }
    text = json.dumps(snap, ensure_ascii=False)
    if contains_advice(text):
        raise ValueError("contour status must not advise")
    return snap


def enable(vault: Vault, *, symbol: str = "BTCUSDT") -> dict[str, Any]:
    """Human switch. Refuses unless hours24 is green. Does not change trading_mode.

    hours24 is checked again after the db is open, so a stale green snapshot
    cannot write on if the tape went red in between.
    """
    snap = status(vault, symbol=symbol)
    if snap["contour"] == "on":
        out = dict(snap)
        out["ok"] = True
        return out
    if not snap["hours24"]:
        raise ContourNotReady("hours24 red")
    mode_before = snap["trading_mode"]
    knowledge = open_knowledge(vault, create=True)
    try:
        if knowledge.meta(META_KEY) == "on":
            return _ok_status(vault, symbol=symbol, mode_before=mode_before)
        ok, _span = hours24(load_tape_events(vault, symbol=symbol), symbol=symbol)
        if not ok:
            raise ContourNotReady("hours24 red")
        knowledge.set_meta(META_KEY, "on")
    finally:
        knowledge.close()
    return _ok_status(vault, symbol=symbol, mode_before=mode_before)


def _ok_status(vault: Vault, *, symbol: str, mode_before: str) -> dict[str, Any]:
    if trading_mode() != mode_before:
        raise RuntimeError("enable must not change trading_mode")
    out = status(vault, symbol=symbol)
    out["ok"] = True
    if out["contour"] != "on":
        raise RuntimeError("enable wrote nothing")
    if out["trading_mode"] != mode_before:
        raise RuntimeError("enable must not change trading_mode")
    return out


def _row(reg: Registry, touch_id: str) -> Touch:
    for touch in reg.touches:
        if touch.touch_id == touch_id:
            return touch
    raise KeyError(touch_id)


def _pick_touch(reg: Registry, touch_id: str | None) -> Touch | None:
    pending = [touch for touch in reg.touches if touch.jury is None]
    if touch_id is not None:
        if not any(touch.touch_id == touch_id for touch in reg.touches):
            raise KeyError(touch_id)
        for touch in pending:
            if touch.touch_id == touch_id:
                return touch
        return None
    if len(pending) > 1:
        raise ValueError("observe needs touch_id when several touches lack jury")
    return pending[0] if pending else None


def observe(
    reg: Registry,
    inp: ObserveIn,
    *,
    contour_on: bool,
    touch_id: str | None = None,
) -> list[Touch]:
    """Glue tape + CAV + ZLG + BTC + jury on **one** touch. No-op when off. No size.

    One ObserveIn is one book / one bar. Several unlabeled touches without
    touch_id is an error — we do not paint a later print with an earlier book.
    A bar of another symbol or tf is an error before any fill — CAV NOISE
    would freeze the first fact. A tape print of
    another symbol is the same error while tape is still empty. A gap of
    another symbol is not a print — skip it. Naive
    news_known_at is an error before any fill while BTC is still empty —
    require_utc after tape/ZLG/CAV leaves a half-card. Naive add.ts is
    an error before any fill while ZLG is still empty — ZLG require_utc
    after fill_tape leaves tape written and gesture empty. mid == print is
    an error only when tape or ZLG is still empty — a BTC-only retry must
    not freeze the card if the book has since centered on the print.
    Missing BTC does not stamp jury. htf_bias=unknown lets btc_bars speak;
    an explicit box/long/short is a fact and does not look at bars.
    n_cav / n_zlg count only the same symbol — ETH history does not unlock BTC.
    """
    if not contour_on:
        return []
    touch = _pick_touch(reg, touch_id)
    if touch is None:
        return []
    tid = touch.touch_id
    zone = reg.zone(touch.zone_id)
    card = inp.card
    if card is not None:
        stopped = _apply_b_card(reg, touch, card)
        if stopped:
            return stopped
    if touch.cav_label is None and (
        inp.cav_bar.symbol != zone.symbol or inp.cav_bar.tf != zone.tf
    ):
        raise ValueError(
            f"observe bar {inp.cav_bar.symbol} {inp.cav_bar.tf} "
            f"is not zone {zone.symbol} {zone.tf}"
        )
    if touch.tape_eaten is None:
        for trade in inp.trades:
            if trade.stream != "trades":
                continue
            if trade.symbol != zone.symbol:
                raise ValueError(f"observe trade {trade.symbol} is not zone {zone.symbol}")
    if touch.btc_regime is None and inp.news_known_at is not None:
        require_utc(inp.news_known_at)
    if touch.gesture is None:
        for add in inp.adds:
            require_utc(add.ts)
    if touch.tape_eaten is None or touch.gesture is None:
        if not inp.book.ready:
            raise ValueError("observe needs a ready book")
        bid, ask = inp.book.best()
        if bid is None or ask is None:
            raise ValueError("observe needs both sides of the book")
        mid = (bid + ask) / 2
        if touch.tape_eaten is None:
            reg.fill_tape(book=inp.book, trades=inp.trades, touch_id=tid)
        live = _row(reg, tid)
        if live.gesture is None:
            hit_side = "bid" if zone.side == "support" else "ask"
            opp_best = ask if hit_side == "bid" else bid
            result = ZLG(tick_size=reg.tick_size, config=reg.config).classify(
                live,
                inp.adds,
                live.trade_qty,
                hit_side=hit_side,
                mid=mid,
                opp_best=opp_best,
            )
            reg.fill_gesture(gesture=result.gesture, touch_id=tid)
    live = _row(reg, tid)
    if live.cav_label is None:
        cav = cav_label(
            zone,
            inp.cav_bar,
            t=live.ts,
            htf_bias=inp.htf_bias,
            closed_bars=inp.closed_bars,
        )
        reg.fill_cav(cav_label=cav, touch_id=tid)
    live = _row(reg, tid)
    if live.btc_regime is None:
        regime = BtcRegime().classify(
            live.ts,
            bars=inp.btc_bars,
            htf_bias=None if inp.htf_bias == "unknown" else inp.htf_bias,
            news_known_at=inp.news_known_at,
        )
        if regime is not None:
            reg.fill_btc(regime=regime, touch_id=tid)
    live = _row(reg, tid)
    if live.btc_regime is None:
        return [live]
    n_cav = sum(
        1
        for row in reg.touches
        if row.cav_label == live.cav_label and reg.zone(row.zone_id).symbol == zone.symbol
    )
    n_zlg = sum(
        1
        for row in reg.touches
        if row.gesture == live.gesture and reg.zone(row.zone_id).symbol == zone.symbol
    )
    stamped = reg.stamp_jury(n_cav=n_cav, n_zlg=n_zlg, touch_id=tid)
    if card is not None and stamped:
        return _paint_b_fields(reg, stamped[0], card)
    return stamped


def _apply_b_card(reg: Registry, touch: Touch, card: CardLive) -> list[Touch] | None:
    """veto / hold / red marks stop roles 1–3. B never opens size."""
    if card.symbol and card.symbol != reg.zone(touch.zone_id).symbol:
        raise ValueError(f"card {card.symbol} is not zone {reg.zone(touch.zone_id).symbol}")
    if card.bearing_verdict == "veto":
        return _paint_b_fields(reg, touch, card, jury="VETO", skip="b_veto")
    if card.bearing_verdict == "hold":
        return _paint_b_fields(reg, touch, card, jury="SILENCE", skip="b_hold")
    if card.bearing_verdict in {"propose", "cut_size"} and not card.context_ok():
        return _paint_b_fields(reg, touch, card, jury="SPLIT", skip="b_marks")
    return None


def _paint_b_fields(
    reg: Registry,
    touch: Touch,
    card: CardLive,
    *,
    jury: str | None = None,
    skip: str | None = None,
) -> list[Touch]:
    vol = card.volume
    fields: dict[str, object] = {
        "bearing_verdict": card.card_voice(),
        "card_id": card.card_id,
        "fib_trend": card.fib_zone,
        "fib_in_05_1": card.fib_zone in {"OTE", "in_05_1"},
        "fib_in_ote_gold": card.fib_zone == "OTE",
        "rsi_tf": "htf",
        "rsi_value": card.rsi_htf,
        "fvg_present": card.fvg_status == "filled",
        "sweep_wick": card.sweep_status == "done",
        "gex_bg": card.gex_bg,
        "ob_status": card.ob_status,
        "bos_status": card.bos_status,
        "poc": vol.poc,
        "vah": vol.vah,
        "val": vol.val,
        "wall_state": vol.walls,
    }
    if jury is not None:
        fields["jury"] = jury
    if skip is not None:
        fields["skip_reason"] = skip
    return reg._patch(touch_id=touch.touch_id, overwrite=True, **fields)


def observe_if_on(
    vault: Vault,
    reg: Registry,
    inp: ObserveIn,
    *,
    touch_id: str | None = None,
) -> list[Touch]:
    """Production glue. Reads the switch. A bool cannot bypass the button."""
    if contour_state(vault) != "on":
        return []
    card = inp.card
    if card is None:
        touch = _pick_touch(reg, touch_id)
        if touch is not None:
            kn = open_knowledge(vault, create=False)
            try:
                raw = kn.get_card_live(reg.zone(touch.zone_id).symbol)
            finally:
                kn.close()
            if raw is not None:
                try:
                    loaded = CardLive.from_payload(raw)
                except (ValueError, KeyError, TypeError):
                    loaded = None
                if loaded is not None and card_is_fresh(
                    loaded, symbol=reg.zone(touch.zone_id).symbol, now=touch.ts
                ):
                    inp = replace(inp, card=loaded)
    return observe(reg, inp, contour_on=True, touch_id=touch_id)
