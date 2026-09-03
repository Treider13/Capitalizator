"""Э2 — desk universe is BTC+ETH+8 alts (top-10). Daily rebalance with hysteresis;
an apply is hot (recorder resubscribes, next load_desk_universe() sees the file).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.screener.refresh import (
    DEFAULT_SIZE,
    HYSTERESIS,
    REFRESH_S,
    apply_universe,
    propose,
    publish_and_apply,
    publish_proposal,
)
from capitalizator.screener.universe import (
    MAX_SYMBOLS,
    REQUIRED_SYMBOLS,
    load_desk_universe,
    load_universe,
    validate_universe,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
OLD = int((NOW - timedelta(days=400)).timestamp() * 1000)


def _inst(symbol: str, *, launch: int = OLD, status: str = "Trading") -> dict:
    return {
        "symbol": symbol,
        "status": status,
        "launchTime": str(launch),
        "contractType": "LinearPerpetual",
        "quoteCoin": "USDT",
    }


def _tick(symbol: str, turnover: str) -> dict:
    return {"symbol": symbol, "turnover24h": turnover}


def test_desk_constants_are_top_ten_daily() -> None:
    assert DEFAULT_SIZE == 10
    assert MAX_SYMBOLS == 10
    assert HYSTERESIS == 2
    assert REFRESH_S == 24 * 3600


def test_packaged_universe_is_ten_majors_first() -> None:
    uni = load_desk_universe()
    assert len(uni.symbols) == 10
    assert uni.symbols[:2] == REQUIRED_SYMBOLS
    assert all(s.endswith("USDT") for s in uni.symbols)


def test_eleven_symbols_rejected() -> None:
    symbols = ["BTCUSDT", "ETHUSDT"] + [f"ALT{i}USDT" for i in range(9)]
    assert len(symbols) == 11
    with pytest.raises(Exception, match="wide universe"):
        validate_universe({"exchange": "bybit", "category": "linear", "symbols": symbols})


def test_hysteresis_keeps_a_current_alt_just_outside_top_n() -> None:
    """Rank 11 of 10 stays (buffer 2). A brand-new rank-9 does not kick it out."""
    current_alts = [f"CUR{i}USDT" for i in range(8)]
    current = validate_universe(
        {"exchange": "bybit", "category": "linear",
         "symbols": ["BTCUSDT", "ETHUSDT", *current_alts]}
    )
    # majors huge; current alts 8..1; HOT is between CUR6 and CUR7 so it would
    # enter a no-hysteresis top-10; CUR7 is rank 11 among all names.
    instruments = [_inst("BTCUSDT"), _inst("ETHUSDT")]
    tickers = [_tick("BTCUSDT", "1000"), _tick("ETHUSDT", "900")]
    for i, name in enumerate(current_alts):
        instruments.append(_inst(name))
        tickers.append(_tick(name, str(80 - i)))  # CUR0=80 … CUR7=73
    instruments.append(_inst("HOTUSDT"))
    tickers.append(_tick("HOTUSDT", "74.5"))  # between CUR6 (74) and CUR7 (73)
    p = propose(
        now=NOW, instruments=instruments, tickers=tickers, current=current,
        size=10, hysteresis=2,
    )
    assert "CUR7USDT" in p.symbols  # kept: rank 11 ≤ 12
    assert "HOTUSDT" not in p.symbols
    assert p.dropped == ()
    assert "HOTUSDT" not in p.added


def test_hysteresis_drops_an_alt_beyond_the_buffer() -> None:
    current = validate_universe(
        {"exchange": "bybit", "category": "linear",
         "symbols": ["BTCUSDT", "ETHUSDT", "KEEPUSDT", *[f"C{i}USDT" for i in range(7)]]}
    )
    instruments = [_inst("BTCUSDT"), _inst("ETHUSDT"), _inst("KEEPUSDT"), _inst("NEWUSDT")]
    tickers = [_tick("BTCUSDT", "1000"), _tick("ETHUSDT", "900"),
               _tick("KEEPUSDT", "1"), _tick("NEWUSDT", "50")]
    for i in range(7):
        instruments.append(_inst(f"C{i}USDT"))
        tickers.append(_tick(f"C{i}USDT", str(80 - i)))
    # seven more liquid names so KEEP falls to rank 13+
    for i in range(7):
        instruments.append(_inst(f"N{i}USDT"))
        tickers.append(_tick(f"N{i}USDT", str(40 - i)))
    p = propose(
        now=NOW, instruments=instruments, tickers=tickers, current=current,
        size=10, hysteresis=2,
    )
    assert "KEEPUSDT" not in p.symbols
    assert "KEEPUSDT" in p.dropped
    assert len(p.symbols) == 10
    assert p.symbols[:2] == ("BTCUSDT", "ETHUSDT")


def test_hot_apply_is_visible_on_the_next_load(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    yaml_path = tmp_path / "universe.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"exchange": "bybit", "category": "linear",
                        "symbols": ["BTCUSDT", "ETHUSDT", "OLDUSDT"]})
    )
    instruments = [_inst("BTCUSDT"), _inst("ETHUSDT"), _inst("SOLUSDT"), _inst("OLDUSDT")]
    tickers = [_tick("BTCUSDT", "9"), _tick("ETHUSDT", "8"),
               _tick("SOLUSDT", "7"), _tick("OLDUSDT", "1")]
    p = publish_proposal(
        kn, now=NOW, instruments=instruments, tickers=tickers,
        universe_path=yaml_path, size=3, hysteresis=0,
    )
    assert p.to_payload()["takes_effect"] == "hot"
    applied = apply_universe(
        kn, proposal_id=p.proposal_id, ack=True, now=NOW, universe_path=yaml_path
    )
    assert applied.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    # same process, no restart: the next read is the new list
    assert load_universe(yaml_path).symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    kn.close()


def test_publish_and_apply_is_the_daily_path(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    yaml_path = tmp_path / "universe.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"exchange": "bybit", "category": "linear",
                        "symbols": ["BTCUSDT", "ETHUSDT"]})
    )
    instruments = [_inst("BTCUSDT"), _inst("ETHUSDT"), _inst("SOLUSDT")]
    tickers = [_tick("BTCUSDT", "9"), _tick("ETHUSDT", "8"), _tick("SOLUSDT", "7")]
    p = publish_and_apply(
        kn, now=NOW, instruments=instruments, tickers=tickers,
        universe_path=yaml_path, size=3, hysteresis=0,
    )
    assert p.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert load_universe(yaml_path).symbols == p.symbols
    assert json.loads(kn.meta("universe_applied"))["proposal_id"] == p.proposal_id
    kn.close()


def test_recorder_set_symbols_subscribes_added_and_drops_removed(tmp_path: Path) -> None:
    from capitalizator.recorder.live_ws import LiveRecorder

    class Spy:
        def __init__(self) -> None:
            self.subs: list[tuple[str, tuple[str, ...]]] = []
            self.unsubs: list[tuple[str, ...]] = []

        def trade_stream(self, syms, cb):
            self.subs.append(("trade", tuple(syms)))

        def orderbook_stream(self, depth, syms, cb):
            self.subs.append(("book", tuple(syms)))

        def ticker_stream(self, syms, cb):
            self.subs.append(("ticker", tuple(syms)))

        def liquidation_stream(self, syms, cb):
            self.subs.append(("liq", tuple(syms)))

        def drop_topics(self, topics):
            self.unsubs.append(tuple(topics))

        def start(self) -> None:
            return None

    spy = Spy()
    rec = LiveRecorder(
        symbols=["BTCUSDT", "ETHUSDT"],
        data_root=tmp_path,
        ws_factory=lambda: spy,
        fetch_snapshot=lambda s: None,
    )
    rec.start()
    assert ("trade", ("BTCUSDT", "ETHUSDT")) in spy.subs
    out = rec.set_symbols(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    assert out["added"] == ("SOLUSDT",) and out["dropped"] == ()
    assert any(s == ("trade", ("SOLUSDT",)) for s in spy.subs)
    out = rec.set_symbols(["BTCUSDT", "SOLUSDT"])
    assert out["dropped"] == ("ETHUSDT",) and out["added"] == ()
    assert rec.symbols == ("BTCUSDT", "SOLUSDT")
    # ETH topics were dropped on the socket
    assert spy.unsubs
    assert any("ETHUSDT" in t for topics in spy.unsubs for t in topics)
