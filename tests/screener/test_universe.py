"""Week-0 universe: BTC+ETH only in repo. Reject 200. No invented alts."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.screener.universe import (
    UniverseError,
    default_week0_path,
    load_universe,
    validate_universe,
)

REPO_FILE = Path(__file__).resolve().parents[2] / "infra" / "universe.week0.yaml"


def test_week0_file_is_btc_eth_only() -> None:
    """PHASE-BUILD: symbols: [BTCUSDT, ETHUSDT]. Alts after 0.1.7, not now."""
    uni = load_universe(REPO_FILE)
    assert uni.exchange == "bybit"
    assert uni.category == "linear"
    assert uni.symbols == ("BTCUSDT", "ETHUSDT")
    assert default_week0_path().resolve() == REPO_FILE.resolve()


def test_missing_eth_rejected() -> None:
    with pytest.raises(UniverseError, match="required"):
        validate_universe(
            {"exchange": "bybit", "category": "linear", "symbols": ["BTCUSDT"]}
        )


def test_missing_btc_rejected() -> None:
    with pytest.raises(UniverseError, match="required"):
        validate_universe(
            {"exchange": "bybit", "category": "linear", "symbols": ["ETHUSDT"]}
        )


def test_two_hundred_rejected() -> None:
    symbols = ["BTCUSDT", "ETHUSDT"] + [f"COIN{i}USDT" for i in range(198)]
    assert len(symbols) == 200
    with pytest.raises(UniverseError, match="wide universe"):
        validate_universe({"exchange": "bybit", "category": "linear", "symbols": symbols})


def test_twenty_five_rejected() -> None:
    symbols = ["BTCUSDT", "ETHUSDT"] + [f"ALT{i}USDT" for i in range(23)]
    assert len(symbols) == 25
    with pytest.raises(UniverseError, match="wide universe"):
        validate_universe({"exchange": "bybit", "category": "linear", "symbols": symbols})


def test_twenty_four_is_legal_shape() -> None:
    from capitalizator.screener.universe import default_desk_path, load_desk_universe

    uni = load_desk_universe()
    assert len(uni.symbols) == 24
    assert uni.symbols[0] == "BTCUSDT"
    assert uni.symbols[1] == "ETHUSDT"
    assert default_desk_path().name == "universe.yaml"


def test_htx_rejected() -> None:
    with pytest.raises(UniverseError, match="HTX"):
        validate_universe(
            {
                "exchange": "htx",
                "category": "linear",
                "symbols": ["BTCUSDT", "ETHUSDT"],
            }
        )


def test_inverse_and_spot_names_rejected() -> None:
    with pytest.raises(UniverseError, match="linear USDT"):
        validate_universe(
            {
                "exchange": "bybit",
                "category": "linear",
                "symbols": ["BTCUSDT", "ETHUSDT", "BTCUSD"],
            }
        )


def test_duplicate_rejected() -> None:
    with pytest.raises(UniverseError, match="duplicate"):
        validate_universe(
            {
                "exchange": "bybit",
                "category": "linear",
                "symbols": ["BTCUSDT", "ETHUSDT", "BTCUSDT"],
            }
        )


def test_future_eight_including_required_is_legal_shape() -> None:
    """After 0.1.7 the file may grow to 8–15. Shape is legal; repo file is still 2."""
    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "BNBUSDT",
        "ADAUSDT",
        "LINKUSDT",
    ]
    uni = validate_universe(
        {"exchange": "bybit", "category": "linear", "symbols": symbols}
    )
    assert uni.symbols == tuple(symbols)
    assert load_universe(REPO_FILE).symbols == ("BTCUSDT", "ETHUSDT")
