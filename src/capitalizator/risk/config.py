"""Risk configuration the operator edits in the console (D-12).

Persisted in SQLite meta as JSON with a version id; every change is also a
hash-chain link so the journal can say which config sized which intent.
Defaults come from infra/phase.yaml (target_risk, max_lev) and infra/gates.yaml f5
(halts) — the numbers a human already wrote there, not new constants.

Law 8 (IMPLEMENTATION.md): risk% = margin% × lev × stop%. The sizer takes the
binding constraint of {target_risk, deposit_share, cap_margin}; it never raises
leverage to hit a number.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from hashlib import blake2s
from typing import Any

from capitalizator.ops.knowledge import Knowledge

META_KEY = "risk_config"
STOP_MODES = frozenset({"structural", "volatility", "hybrid"})
TRAIL_MODES = frozenset({"structure", "exchange_trailing", "both"})


@dataclass(frozen=True)
class RiskConfig:
    # Fraction of equity used as margin per trade ("какая часть депозита в сделку").
    deposit_share_per_trade: Decimal = Decimal("0.10")
    # Fraction of equity lost if the stop is hit.
    target_risk_pct: Decimal = Decimal("0.01")
    max_lev: Decimal = Decimal("3")
    max_open_positions: int = 1
    max_intents_per_session: int = 3
    day_halt: Decimal = Decimal("-0.03")
    week_halt: Decimal = Decimal("-0.06")
    peak_kill: Decimal = Decimal("-0.25")
    # A 1R win must be at least this many round-trip fees (EV gate).
    fee_multiple_min: Decimal = Decimal("5")
    stop_mode: str = "hybrid"
    trail_mode: str = "both"
    allow_night: bool = False
    # Paper / demo equity used until a wallet is read from the exchange.
    paper_equity: Decimal = Decimal("100000")
    version: int = 1
    config_id: str = ""

    def __post_init__(self) -> None:
        if not (Decimal("0") < self.deposit_share_per_trade <= Decimal("1")):
            raise ValueError("deposit_share_per_trade must be in (0, 1]")
        if not (Decimal("0") < self.target_risk_pct <= Decimal("0.05")):
            raise ValueError("target_risk_pct must be in (0, 0.05]")
        if self.max_lev <= 0 or self.max_lev > Decimal("10"):
            raise ValueError("max_lev must be in (0, 10]")
        if self.max_open_positions < 1 or self.max_intents_per_session < 1:
            raise ValueError("positions / intents per session must be >= 1")
        for name in ("day_halt", "week_halt", "peak_kill"):
            if getattr(self, name) >= 0:
                raise ValueError(f"{name} must be negative")
        if self.fee_multiple_min < 1:
            raise ValueError("fee_multiple_min must be >= 1")
        if self.stop_mode not in STOP_MODES:
            raise ValueError(f"stop_mode must be one of {sorted(STOP_MODES)}")
        if self.trail_mode not in TRAIL_MODES:
            raise ValueError(f"trail_mode must be one of {sorted(TRAIL_MODES)}")
        if self.paper_equity <= 0:
            raise ValueError("paper_equity must be > 0")
        if not self.config_id:
            object.__setattr__(self, "config_id", self._digest())

    def _digest(self) -> str:
        body = {k: str(v) for k, v in asdict(self).items() if k != "config_id"}
        return blake2s(json.dumps(body, sort_keys=True).encode(), digest_size=8).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> RiskConfig:
        dec = (
            "deposit_share_per_trade",
            "target_risk_pct",
            "max_lev",
            "day_halt",
            "week_halt",
            "peak_kill",
            "fee_multiple_min",
            "paper_equity",
        )
        kwargs: dict[str, Any] = {}
        for key, value in raw.items():
            if key in dec:
                kwargs[key] = Decimal(str(value))
            elif key in {"max_open_positions", "max_intents_per_session", "version"}:
                kwargs[key] = int(value)
            elif key in {"stop_mode", "trail_mode", "config_id"}:
                kwargs[key] = str(value)
            elif key == "allow_night":
                kwargs[key] = bool(value)
            else:
                raise ValueError(f"unknown risk_config key: {key}")
        return cls(**kwargs)

    def with_changes(self, **changes: Any) -> RiskConfig:
        nxt = replace(self, **changes, config_id="", version=self.version + 1)
        return nxt

    def implied_risk(self, *, lev: Decimal, stop_frac: Decimal) -> Decimal:
        """Law 8: what deposit_share × lev × stop% would risk."""
        return self.deposit_share_per_trade * lev * stop_frac


def load_risk_config(knowledge: Knowledge) -> RiskConfig:
    raw = knowledge.meta(META_KEY) if knowledge.available() else None
    if raw is None:
        return RiskConfig()
    try:
        return RiskConfig.from_payload(json.loads(raw))
    except (ValueError, json.JSONDecodeError):
        return RiskConfig()


def save_risk_config(knowledge: Knowledge, cfg: RiskConfig, *, ack: bool) -> RiskConfig:
    """Human change with ack. Writes meta + a hash link so the journal can cite it."""
    if not ack:
        raise ValueError("ack required to change risk config")
    body = json.dumps(cfg.to_payload(), sort_keys=True, ensure_ascii=False)
    knowledge.set_meta(META_KEY, body)
    knowledge.append_link(
        json.dumps(
            {"k": "risk_config", "config_id": cfg.config_id, "version": cfg.version},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return cfg
