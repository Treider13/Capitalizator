"""Versioned operational budgets, separate from fitted market parameters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    symbols: tuple[str, ...] = (
        "BTCUSDT",
        "ETHUSDT",
        "XAUUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "DOGEUSDT",
    )
    workers: int = 4
    queue_capacity: int = 4096
    queue_quantum: int = 32
    block_trades: int = 64
    block_seconds: float = 5.0
    block_max_seconds: float = 30.0
    context_blocks: int = 32
    horizon_blocks: int = 4
    confirmation_blocks: int = 1
    demo_samples: int = 64
    live_samples: int = 512
    training_rows: int = 8192
    retrain_samples: int = 64
    risk_fraction: float = 0.0025
    day_loss_fraction: float = 0.02
    portfolio_risk_fraction: float = 0.01
    margin_fraction: float = 0.2
    trade_margin_fraction: float = 0.1
    max_stop_fraction: float = 0.05
    leverage: float = 2.0
    max_positions: int = 2
    participation: float = 0.01
    max_spread_bps: float = 10.0
    max_data_age_s: float = 5.0
    account_age_s: float = 15.0
    entry_ttl_s: float = 10.0
    contract_timeout_s: float = 120.0
    max_hold_s: float = 900.0
    reconcile_s: float = 5.0
    http_timeout_s: float = 5.0
    confidence_alpha: float = 0.1
    minimum_rr: float = 2.0
    news_pre_minutes: int = 15
    news_post_minutes: int = 15
    api_port: int = 8082
    archive_batch: int = 10000
    demo_maker_fee: float = 0.0002
    demo_taker_fee: float = 0.00055
    minimum_free_disk_bytes: int = 536870912
    news_stale_s: float = 180.0
    model_max_age_s: float = 3600.0
    news_poll_s: float = 60.0
    context_poll_s: float = 60.0
    chart_refresh_s: float = 0.2
    macro_poll_s: float = 3600.0
    macro_stale_s: float = 86400.0

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be nonempty and unique")
        if any(
            not isinstance(s, str)
            or not s.isascii()
            or not s.isalnum()
            or not s.isupper()
            or not s.endswith("USDT")
            for s in self.symbols
        ):
            raise ValueError("only USDT linear symbols supported")
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "symbols":
                continue
            expected = int if f.type == "int" else float
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{f.name} must be numeric")
            if expected is int and not isinstance(value, int):
                raise ValueError(f"{f.name} must be an integer")
            if isinstance(value, (int, float)) and (not 0 < value < float("inf")):
                raise ValueError(f"{f.name} must be finite and positive")
        for name in (
            "risk_fraction",
            "day_loss_fraction",
            "portfolio_risk_fraction",
            "margin_fraction",
            "max_stop_fraction",
            "participation",
            "confidence_alpha",
        ):
            if getattr(self, name) >= 1:
                raise ValueError(f"{name} must be < 1")
        if self.trade_margin_fraction > 1:
            raise ValueError("trade_margin_fraction must be <= 1")
        if not 1 <= self.leverage <= 10:
            raise ValueError("leverage must be between 1 and 10")
        if self.confirmation_blocks >= self.horizon_blocks:
            raise ValueError("confirmation must leave a forecast horizon")
        if self.training_rows < self.live_samples or self.live_samples < self.demo_samples:
            raise ValueError("training_rows >= live_samples >= demo_samples required")
        if self.minimum_rr < 2:
            raise ValueError("minimum_rr must be >= 2")
        if self.block_max_seconds < self.block_seconds:
            raise ValueError("block_max_seconds must be >= block_seconds")
        if self.api_port > 65535:
            raise ValueError("api_port exceeds 65535")
        if self.confirmation_blocks != 1:
            raise ValueError(
                "reaction targets are trained for the next block; confirmation_blocks must be 1"
            )

    @property
    def version(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {"policy": "fusion-9-exchange-time", **asdict(self)}, sort_keys=True
            ).encode()
        ).hexdigest()[:16]

    @classmethod
    def load(cls, path: Path | None) -> Config:
        if path is None:
            return cls()
        data = json.loads(path.read_text())
        if "symbols" in data:
            data["symbols"] = tuple(data["symbols"])
        return cls(**data)
