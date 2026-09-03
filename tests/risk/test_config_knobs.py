"""Knobs that cut size or refuse entries live in RiskConfig — validated, versioned,
visible on /ops — not as class constants in the desk (audit Н10)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.risk.config import RiskConfig


def test_defaults_match_the_former_constants() -> None:
    cfg = RiskConfig()
    assert cfg.sentiment_greed == 80
    assert cfg.sentiment_mult == Decimal("0.7")
    assert cfg.fragility_thin_z == Decimal("-1")


def test_payload_round_trip_keeps_the_new_knobs() -> None:
    cfg = RiskConfig(sentiment_greed=75, sentiment_mult=Decimal("0.5"),
                     fragility_thin_z=Decimal("-1.5"))
    again = RiskConfig.from_payload(cfg.to_payload())
    assert again.sentiment_greed == 75
    assert again.sentiment_mult == Decimal("0.5")
    assert again.fragility_thin_z == Decimal("-1.5")
    assert again.config_id == cfg.config_id


@pytest.mark.parametrize(
    "changes",
    [
        {"sentiment_greed": 49},
        {"sentiment_greed": 101},
        {"sentiment_mult": Decimal("0")},
        {"sentiment_mult": Decimal("1.2")},  # sentiment only cuts, never opens
        {"fragility_thin_z": Decimal("0")},  # thin means below the norm
        {"fragility_thin_z": Decimal("0.5")},
    ],
)
def test_out_of_range_knobs_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RiskConfig(**changes)  # type: ignore[arg-type]


def test_console_strings_are_parsed() -> None:
    raw = RiskConfig().to_payload()
    raw.update({"sentiment_greed": "85", "sentiment_mult": "0.6", "fragility_thin_z": "-2"})
    raw.pop("config_id")
    cfg = RiskConfig.from_payload(raw)
    assert (cfg.sentiment_greed, cfg.sentiment_mult, cfg.fragility_thin_z) == (
        85, Decimal("0.6"), Decimal("-2"))
