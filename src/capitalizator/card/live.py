"""CardLive — contour B output. Never sends an order. Never reads keys.

bearing_verdict + macro_multiplier + labels land in knowledge (claim id b_card:SYMBOL).
A reads this before roles. veto → skip/flatten. Red marks → SPLIT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from capitalizator.card.gex import gex_is_green
from capitalizator.types import require_utc

Bearing = Literal["veto", "cut_size", "propose", "hold"]
FibZone = Literal["OTE", "in_05_1", "forbidden_0_05", "none"]
SweepStatus = Literal["done", "pending", "none"]
FvgStatus = Literal["filled", "open", "none"]
Regime = Literal["trend", "range", "none"]
SmcStatus = Literal["bull", "bear"]

MARK_KEYS = ("fib", "sweep", "gex", "fvg", "jury_b")
REQUIRED_MARKS = ("fib", "sweep", "fvg", "jury_b")


@dataclass(frozen=True)
class VolumeSnapshot:
    poc: str | None = None
    vah: str | None = None
    val: str | None = None
    vwap: str | None = None
    delta: str | None = None
    rvol: str | None = None
    eaten_levels: str | None = None
    walls: str | None = None
    a_price: str | None = None
    a_volume: str | None = None
    a_delta: str | None = None
    a_wall: str | None = None


@dataclass(frozen=True)
class CardLive:
    symbol: str
    bearing_verdict: Bearing
    known_at: datetime
    macro_multiplier: Decimal = Decimal("1")
    fib_zone: FibZone = "none"
    fib_level: str | None = None
    rsi_htf: str | None = None
    gex_bg: str | None = None
    fvg_status: FvgStatus = "none"
    sweep_status: SweepStatus = "none"
    ob_status: SmcStatus | None = None
    bos_status: SmcStatus | None = None
    market_regime: Regime = "none"
    jury_b_for: int = 0
    jury_b_n: int = 0
    volume: VolumeSnapshot = field(default_factory=VolumeSnapshot)
    pluses: tuple[str, ...] = ()
    minuses: tuple[str, ...] = ()
    card_id: str = ""
    venue: Literal["perp", "spot_proposal"] = "perp"

    def __post_init__(self) -> None:
        require_utc(self.known_at)
        if self.macro_multiplier not in {Decimal("1"), Decimal("0.5"), Decimal("0.3")}:
            raise ValueError("macro_multiplier must be 1, 0.5, or 0.3")
        if not self.minuses and self.bearing_verdict != "hold":
            raise ValueError("card must carry at least one minus")
        n_atoms = len(self.pluses) + len(self.minuses)
        if self.bearing_verdict != "hold" and (n_atoms < 5 or n_atoms > 7):
            raise ValueError("card must have 5–7 atoms")
        if not self.card_id:
            object.__setattr__(self, "card_id", uuid4().hex)

    def mark_green(self) -> dict[str, bool | None]:
        """None-marks are red. GEX None is optional (skipped, does not vote)."""
        return {
            "fib": self.fib_zone in {"OTE", "in_05_1"},
            "sweep": self.sweep_status == "done",
            "gex": gex_is_green(self.gex_bg),
            "fvg": self.fvg_status == "filled",
            "jury_b": self.jury_b_n == 0 or self.jury_b_for >= 3,
        }

    def green_count(self) -> int:
        return sum(1 for ok in self.mark_green().values() if ok is True)

    def context_ok(self) -> bool:
        if self.fib_zone == "forbidden_0_05" or self.sweep_status == "pending":
            return False
        marks = self.mark_green()
        if any(marks[key] is not True for key in REQUIRED_MARKS):
            return False
        return self.green_count() >= 4

    def card_voice(self) -> str:
        """Map onto jury card_bearing_verdict."""
        if self.bearing_verdict == "veto":
            return "veto"
        if self.bearing_verdict in {"propose", "cut_size"}:
            return "propose"
        return "hold"

    def to_payload(self) -> dict[str, Any]:
        vol = self.volume
        return {
            "symbol": self.symbol,
            "bearing_verdict": self.bearing_verdict,
            "known_at": self.known_at.isoformat(),
            "macro_multiplier": str(self.macro_multiplier),
            "fib_zone": self.fib_zone,
            "fib_level": self.fib_level,
            "rsi_htf": self.rsi_htf,
            "gex_bg": self.gex_bg,
            "fvg_status": self.fvg_status,
            "sweep_status": self.sweep_status,
            "ob_status": self.ob_status,
            "bos_status": self.bos_status,
            "market_regime": self.market_regime,
            "jury_b_for": self.jury_b_for,
            "jury_b_n": self.jury_b_n,
            "volume": {
                "poc": vol.poc,
                "vah": vol.vah,
                "val": vol.val,
                "vwap": vol.vwap,
                "delta": vol.delta,
                "rvol": vol.rvol,
                "eaten_levels": vol.eaten_levels,
                "walls": vol.walls,
                "a_price": vol.a_price,
                "a_volume": vol.a_volume,
                "a_delta": vol.a_delta,
                "a_wall": vol.a_wall,
            },
            "pluses": list(self.pluses),
            "minuses": list(self.minuses),
            "card_id": self.card_id,
            "venue": self.venue,
        }

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> CardLive:
        vol = raw.get("volume") if isinstance(raw.get("volume"), dict) else {}
        known = raw["known_at"]
        if isinstance(known, str):
            text = known.replace("Z", "+00:00") if known.endswith("Z") else known
            known_at = datetime.fromisoformat(text)
        else:
            known_at = known
        return cls(
            symbol=str(raw["symbol"]),
            bearing_verdict=raw["bearing_verdict"],  # type: ignore[arg-type]
            known_at=known_at,
            macro_multiplier=Decimal(str(raw.get("macro_multiplier") or "1")),
            fib_zone=raw.get("fib_zone") or "none",  # type: ignore[arg-type]
            fib_level=raw.get("fib_level"),
            rsi_htf=raw.get("rsi_htf"),
            gex_bg=raw.get("gex_bg"),
            fvg_status=raw.get("fvg_status") or "none",  # type: ignore[arg-type]
            sweep_status=raw.get("sweep_status") or "none",  # type: ignore[arg-type]
            ob_status=raw.get("ob_status"),
            bos_status=raw.get("bos_status"),
            market_regime=raw.get("market_regime") or "none",  # type: ignore[arg-type]
            jury_b_for=int(raw.get("jury_b_for") or 0),
            jury_b_n=int(raw.get("jury_b_n") or 0),
            volume=VolumeSnapshot(
                poc=vol.get("poc"),
                vah=vol.get("vah"),
                val=vol.get("val"),
                vwap=vol.get("vwap"),
                delta=vol.get("delta"),
                rvol=vol.get("rvol"),
                eaten_levels=vol.get("eaten_levels"),
                walls=vol.get("walls"),
                a_price=vol.get("a_price"),
                a_volume=vol.get("a_volume"),
                a_delta=vol.get("a_delta"),
                a_wall=vol.get("a_wall"),
            ),
            pluses=tuple(str(x) for x in (raw.get("pluses") or ())),
            minuses=tuple(str(x) for x in (raw.get("minuses") or ())),
            card_id=str(raw.get("card_id") or ""),
            venue=raw.get("venue") or "perp",  # type: ignore[arg-type]
        )


def card_is_fresh(
    card: CardLive,
    *,
    symbol: str,
    now: datetime,
    ttl_s: float | None = None,
) -> bool:
    """False when the claim is for another pair or older than CARD_TTL_S."""
    from capitalizator.card.params import CARD_TTL_S

    if card.symbol != symbol:
        return False
    age = (now - card.known_at).total_seconds()
    limit = CARD_TTL_S if ttl_s is None else ttl_s
    return 0 <= age <= limit


def touch_line(*, symbol: str, card: CardLive | None, jury: str | None) -> str:
    """Operator line. English tokens only — no advice verbs."""
    b = card.bearing_verdict if card is not None else "hold"
    a = jury or "none"
    rsi = card.rsi_htf if card and card.rsi_htf else "-"
    fib = "-"
    if card is not None and card.fib_level:
        fib = f"{card.fib_level}({card.fib_zone})"
    elif card is not None:
        fib = card.fib_zone
    fvg = "yes" if card and card.fvg_status == "filled" else "no"
    sweep = "yes" if card and card.sweep_status == "done" else "no"
    gex = card.gex_bg if card and card.gex_bg else "-"
    rvol = card.volume.rvol if card and card.volume.rvol else "-"
    return (
        f"[TOUCH] {symbol} | B:{b} | A:{a} | RSI:{rsi} | Fib:{fib} "
        f"| FVG:{fvg} | Sweep:{sweep} | GEX:{gex} | RVOL:{rvol}"
    )


def fib_zone_at(*, low: Decimal, high: Decimal, price: Decimal) -> tuple[FibZone, str]:
    """Retrace from high. 0–0.5 forbidden, 0.618–0.786 OTE, else 0.5–1."""
    if high <= low:
        return "none", "0"
    retrace = (high - price) / (high - low)
    level = f"{retrace:.3f}"
    if retrace < 0 or retrace > 1:
        return "none", level
    if retrace < Decimal("0.5"):
        return "forbidden_0_05", level
    if Decimal("0.618") <= retrace <= Decimal("0.786"):
        return "OTE", level
    return "in_05_1", level
