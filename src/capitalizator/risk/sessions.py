"""Session policy: the desk trades 24/7, the *send* rules depend on the UTC window.

Replaces the single 16:30–19:30 MSK gate (`risk/session.py`, kept for legacy callers)
with a table from `infra/sessions.yaml`: per window — allowed ideas, size multiplier,
stop buffer `k_atr`, intent budget, symbol policy, 5x permission; plus daily / weekly
blackouts, a funding-settlement blackout and the weekend override.

Design rules (same laws as the rest of the risk package):
  * the policy only refuses or cuts — it never raises size above the operator's
    `target_risk_pct`, never raises leverage, never invents a window;
  * every decision returns a reason string that goes to the journal;
  * unknown yaml keys are an error, windows must tile the 24h exactly;
  * time is tz-aware UTC (`require_utc`); the file's `tz` must be UTC.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.risk.session import us_data_day
from capitalizator.types import require_utc

POLICY_KEYS = frozenset(
    {
        "tz",
        "majors",
        "windows",
        "weekend",
        "blackouts",
        "funding_blackout_min",
        "us_data_day_block_windows",
    }
)
WINDOW_KEYS = frozenset(
    {"start", "end", "ideas", "size_mult", "k_atr", "budget", "symbols", "lev_5x_ok"}
)
WEEKEND_KEYS = frozenset({"ideas", "size_mult", "k_atr", "budget", "symbols", "lev_5x_ok"})
BLACKOUT_KEYS = frozenset({"name", "kind", "start", "end", "weekday", "applies_to"})
IDEAS = frozenset({"bounce", "spring", "breakout"})
SYMBOL_POLICIES = frozenset(
    {"none", "majors", "top5_plus_majors", "top10_plus_screen", "all"}
)
APPLIES = frozenset({"all", "non_majors"})
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DAY_END = time(23, 59, 59, 999999)
WEEKEND_NAME = "weekend"


class SessionPolicyError(ValueError):
    """sessions.yaml is not a legal policy."""


@dataclass(frozen=True)
class Window:
    name: str
    start: time
    end: time  # exclusive; "24:00" is stored as DAY_END inclusive
    end_is_midnight: bool
    ideas: frozenset[str]
    size_mult: Decimal
    k_atr: Decimal
    budget: int
    symbols: str
    lev_5x_ok: bool

    def contains(self, stamp: time) -> bool:
        if self.end_is_midnight:
            return self.start <= stamp
        return self.start <= stamp < self.end


@dataclass(frozen=True)
class Blackout:
    name: str
    kind: str  # daily | weekly
    start: time
    end: time
    end_is_midnight: bool
    weekday: int | None
    applies_to: str

    def hits(self, when: datetime, *, is_major: bool) -> bool:
        if self.applies_to == "non_majors" and is_major:
            return False
        if self.kind == "weekly" and when.weekday() != self.weekday:
            return False
        stamp = when.timetz().replace(tzinfo=None)
        if self.end_is_midnight:
            return self.start <= stamp
        return self.start <= stamp < self.end


@dataclass(frozen=True)
class WindowState:
    """What the policy says about this instant, before symbol / idea checks."""

    name: str
    weekend: bool
    ideas: frozenset[str]
    size_mult: Decimal
    k_atr: Decimal
    budget: int
    symbols: str
    lev_5x_ok: bool
    budget_key: str


@dataclass(frozen=True)
class Verdict:
    allow: bool
    reason: str
    state: WindowState

    def as_tuple(self) -> tuple[bool, str]:
        return self.allow, self.reason


def _find_yaml() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "sessions.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/sessions.yaml missing")


def _parse_time(raw: Any, *, field: str) -> tuple[time, bool]:
    text = str(raw)
    if text == "24:00":
        return DAY_END, True
    try:
        return time.fromisoformat(text), False
    except ValueError as exc:
        raise SessionPolicyError(f"{field}: bad time {text!r}") from exc


def _decimal(raw: Any, *, field: str, lo: Decimal, hi: Decimal) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise SessionPolicyError(f"{field}: not a number {raw!r}") from exc
    if not (lo <= value <= hi):
        raise SessionPolicyError(f"{field}: {value} outside [{lo}, {hi}]")
    return value


def _ideas(raw: Any, *, field: str) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise SessionPolicyError(f"{field}: ideas must be a list")
    names = frozenset(str(x) for x in raw)
    unknown = names - IDEAS
    if unknown:
        raise SessionPolicyError(f"{field}: unknown ideas {sorted(unknown)}")
    return names


def _check_keys(body: Mapping[str, Any], allowed: frozenset[str], *, field: str) -> None:
    extra = set(body) - allowed
    if extra:
        raise SessionPolicyError(f"{field}: unknown keys {sorted(extra)}")


def _window(name: str, body: Any) -> Window:
    if not isinstance(body, Mapping):
        raise SessionPolicyError(f"windows.{name}: must be a mapping")
    _check_keys(body, WINDOW_KEYS, field=f"windows.{name}")
    missing = WINDOW_KEYS - set(body)
    if missing:
        raise SessionPolicyError(f"windows.{name}: missing {sorted(missing)}")
    start, start_mid = _parse_time(body["start"], field=f"windows.{name}.start")
    if start_mid:
        raise SessionPolicyError(f"windows.{name}: start cannot be 24:00")
    end, end_mid = _parse_time(body["end"], field=f"windows.{name}.end")
    if not end_mid and end <= start:
        raise SessionPolicyError(f"windows.{name}: end must be after start")
    symbols = str(body["symbols"])
    if symbols not in SYMBOL_POLICIES:
        raise SessionPolicyError(f"windows.{name}: unknown symbols policy {symbols!r}")
    budget = body["budget"]
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise SessionPolicyError(f"windows.{name}: budget must be an int >= 0")
    lev_ok = body["lev_5x_ok"]
    if not isinstance(lev_ok, bool):
        raise SessionPolicyError(f"windows.{name}: lev_5x_ok must be a bool")
    return Window(
        name=name,
        start=start,
        end=end,
        end_is_midnight=end_mid,
        ideas=_ideas(body["ideas"], field=f"windows.{name}"),
        size_mult=_decimal(
            body["size_mult"], field=f"windows.{name}.size_mult", lo=Decimal(0), hi=Decimal(1)
        ),
        k_atr=_decimal(
            body["k_atr"], field=f"windows.{name}.k_atr", lo=Decimal("0.1"), hi=Decimal("3")
        ),
        budget=budget,
        symbols=symbols,
        lev_5x_ok=lev_ok,
    )


def _weekend(body: Any) -> Window:
    if not isinstance(body, Mapping):
        raise SessionPolicyError("weekend: must be a mapping")
    _check_keys(body, WEEKEND_KEYS, field="weekend")
    missing = WEEKEND_KEYS - set(body)
    if missing:
        raise SessionPolicyError(f"weekend: missing {sorted(missing)}")
    return _window(
        WEEKEND_NAME, {**dict(body), "start": "00:00", "end": "24:00"}
    )


def _blackout(idx: int, body: Any) -> Blackout:
    field = f"blackouts[{idx}]"
    if not isinstance(body, Mapping):
        raise SessionPolicyError(f"{field}: must be a mapping")
    _check_keys(body, BLACKOUT_KEYS, field=field)
    for key in ("name", "kind", "start", "end", "applies_to"):
        if key not in body:
            raise SessionPolicyError(f"{field}: missing {key}")
    kind = str(body["kind"])
    if kind not in {"daily", "weekly"}:
        raise SessionPolicyError(f"{field}: kind must be daily|weekly")
    weekday: int | None = None
    if kind == "weekly":
        raw_day = str(body.get("weekday") or "").lower()
        if raw_day not in WEEKDAYS:
            raise SessionPolicyError(f"{field}: weekly blackout needs weekday mon..sun")
        weekday = WEEKDAYS[raw_day]
    elif "weekday" in body:
        raise SessionPolicyError(f"{field}: weekday only for weekly blackouts")
    start, start_mid = _parse_time(body["start"], field=f"{field}.start")
    if start_mid:
        raise SessionPolicyError(f"{field}: start cannot be 24:00")
    end, end_mid = _parse_time(body["end"], field=f"{field}.end")
    if not end_mid and end <= start:
        raise SessionPolicyError(f"{field}: end must be after start")
    applies = str(body["applies_to"])
    if applies not in APPLIES:
        raise SessionPolicyError(f"{field}: applies_to must be all|non_majors")
    return Blackout(
        name=str(body["name"]),
        kind=kind,
        start=start,
        end=end,
        end_is_midnight=end_mid,
        weekday=weekday,
        applies_to=applies,
    )


def _check_tiling(windows: Sequence[Window]) -> None:
    """Windows must cover 00:00 → 24:00 exactly once, in order."""
    ordered = sorted(windows, key=lambda w: w.start)
    if not ordered:
        raise SessionPolicyError("windows: at least one window is required")
    if ordered[0].start != time(0, 0):
        raise SessionPolicyError("windows: first window must start at 00:00")
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        if prev.end_is_midnight:
            raise SessionPolicyError(f"windows: {prev.name} ends at 24:00 but {nxt.name} follows")
        if prev.end != nxt.start:
            raise SessionPolicyError(
                f"windows: gap or overlap between {prev.name} ({prev.end}) "
                f"and {nxt.name} ({nxt.start})"
            )
    if not ordered[-1].end_is_midnight:
        raise SessionPolicyError("windows: last window must end at 24:00")


def load_policy_yaml(path: Path | None = None) -> dict[str, Any]:
    target = path if path is not None else _find_yaml()
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SessionPolicyError("sessions.yaml must be a mapping")
    return raw


class SessionPolicy:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        _check_keys(raw, POLICY_KEYS, field="sessions")
        missing = POLICY_KEYS - set(raw)
        if missing:
            raise SessionPolicyError(f"sessions: missing {sorted(missing)}")
        if str(raw["tz"]).upper() != "UTC":
            raise SessionPolicyError("sessions.tz must be UTC")
        majors_raw = raw["majors"]
        if not isinstance(majors_raw, list) or not majors_raw:
            raise SessionPolicyError("sessions.majors must be a non-empty list")
        self.majors: frozenset[str] = frozenset(str(s) for s in majors_raw)
        windows_raw = raw["windows"]
        if not isinstance(windows_raw, Mapping) or not windows_raw:
            raise SessionPolicyError("sessions.windows must be a non-empty mapping")
        if WEEKEND_NAME in windows_raw:
            raise SessionPolicyError(f"windows: {WEEKEND_NAME!r} is reserved")
        self.windows: tuple[Window, ...] = tuple(
            sorted((_window(str(n), b) for n, b in windows_raw.items()), key=lambda w: w.start)
        )
        _check_tiling(self.windows)
        self.weekend: Window = _weekend(raw["weekend"])
        blackouts_raw = raw["blackouts"]
        if blackouts_raw is None:
            blackouts_raw = []
        if not isinstance(blackouts_raw, list):
            raise SessionPolicyError("sessions.blackouts must be a list")
        self.blackouts: tuple[Blackout, ...] = tuple(
            _blackout(i, b) for i, b in enumerate(blackouts_raw)
        )
        names = [b.name for b in self.blackouts]
        if len(set(names)) != len(names):
            raise SessionPolicyError("blackouts: duplicate names")
        fb = raw["funding_blackout_min"]
        if not isinstance(fb, int) or isinstance(fb, bool) or fb < 0 or fb > 60:
            raise SessionPolicyError("funding_blackout_min must be an int in [0, 60]")
        self.funding_blackout = timedelta(minutes=fb)
        blocked = raw["us_data_day_block_windows"]
        if blocked is None:
            blocked = []
        if not isinstance(blocked, list):
            raise SessionPolicyError("us_data_day_block_windows must be a list")
        known = {w.name for w in self.windows}
        unknown = set(str(x) for x in blocked) - known
        if unknown:
            raise SessionPolicyError(
                f"us_data_day_block_windows: unknown windows {sorted(unknown)}"
            )
        self.us_data_block: frozenset[str] = frozenset(str(x) for x in blocked)

    @classmethod
    def load(cls, path: Path | None = None) -> SessionPolicy:
        return cls(load_policy_yaml(path))

    # --- lookups ---------------------------------------------------------------------
    def is_major(self, symbol: str) -> bool:
        return symbol in self.majors

    def window_named(self, name: str) -> Window:
        if name == WEEKEND_NAME:
            return self.weekend
        for w in self.windows:
            if w.name == name:
                return w
        raise KeyError(name)

    def names(self) -> tuple[str, ...]:
        return tuple(w.name for w in self.windows) + (WEEKEND_NAME,)

    def clock_window(self, now: datetime) -> Window:
        """The tiling window for this instant, ignoring the weekend override."""
        when = require_utc(now)
        stamp = when.timetz().replace(tzinfo=None)
        for w in self.windows:
            if w.contains(stamp):
                return w
        raise RuntimeError("windows do not tile the day")  # unreachable after _check_tiling

    def window(self, now: datetime) -> WindowState:
        when = require_utc(now)
        clock = self.clock_window(when)
        weekend = when.weekday() >= 5
        src = self.weekend if weekend else clock
        name = WEEKEND_NAME if weekend else clock.name
        return WindowState(
            name=name,
            weekend=weekend,
            ideas=src.ideas,
            size_mult=src.size_mult,
            k_atr=src.k_atr,
            budget=src.budget,
            symbols=src.symbols,
            lev_5x_ok=src.lev_5x_ok,
            budget_key=f"{when.date().isoformat()}:{name}",
        )

    def clock_name(self, now: datetime) -> str:
        """Journal label: the tiling window even on weekends (weekend flag is separate)."""
        return self.clock_window(now).name

    def active_blackouts(self, now: datetime, *, symbol: str | None = None) -> tuple[str, ...]:
        when = require_utc(now)
        is_major = symbol is not None and self.is_major(symbol)
        return tuple(b.name for b in self.blackouts if b.hits(when, is_major=is_major))

    def symbol_allowed(
        self,
        state: WindowState,
        symbol: str,
        *,
        rank: Mapping[str, int] | None,
        screened: frozenset[str] | None,
    ) -> tuple[bool, str]:
        policy = state.symbols
        if policy == "none":
            return False, "symbols:none"
        if policy == "all":
            return True, "ok"
        if self.is_major(symbol):
            return True, "ok"
        if policy == "majors":
            return False, "symbols:majors_only"
        r = None if rank is None else rank.get(symbol)
        if policy == "top5_plus_majors":
            if r is not None and r <= 5:
                return True, "ok"
            return False, "symbols:not_top5"
        # top10_plus_screen
        if r is not None and r <= 10:
            return True, "ok"
        if screened is not None and symbol in screened:
            return True, "ok"
        return False, "symbols:not_top10_not_screened"

    # --- the decision --------------------------------------------------------------------
    def allows(
        self,
        now: datetime,
        calendar: Sequence[NewsRow] | None = None,
        *,
        idea: str | None = None,
        symbol: str | None = None,
        lev: Decimal = Decimal("3"),
        no_us_today: bool = False,
        next_funding_at: datetime | None = None,
        rank: Mapping[str, int] | None = None,
        screened: frozenset[str] | None = None,
    ) -> tuple[bool, str]:
        return self.decide(
            now,
            calendar,
            idea=idea,
            symbol=symbol,
            lev=lev,
            no_us_today=no_us_today,
            next_funding_at=next_funding_at,
            rank=rank,
            screened=screened,
        ).as_tuple()

    def decide(
        self,
        now: datetime,
        calendar: Sequence[NewsRow] | None = None,
        *,
        idea: str | None = None,
        symbol: str | None = None,
        lev: Decimal = Decimal("3"),
        no_us_today: bool = False,
        next_funding_at: datetime | None = None,
        rank: Mapping[str, int] | None = None,
        screened: frozenset[str] | None = None,
    ) -> Verdict:
        """Time, idea, symbol, funding and 5x rules. Budget is the Account's job.

        `no_us_today` is the legacy operator flag: it only lifts the US-data-day
        block, never a window or a blackout.
        """
        when = require_utc(now)
        state = self.window(when)
        if not state.ideas or state.budget <= 0 or state.size_mult <= 0:
            return Verdict(False, f"window:{state.name}:closed", state)
        if idea is not None and idea not in state.ideas:
            return Verdict(False, f"window:{state.name}:idea:{idea}", state)
        if lev >= 5 and not state.lev_5x_ok:
            return Verdict(False, f"window:{state.name}:no_5x", state)
        hits = self.active_blackouts(when, symbol=symbol)
        if hits:
            return Verdict(False, f"blackout:{hits[0]}", state)
        if (
            not no_us_today
            and state.name in self.us_data_block
            and calendar
            and us_data_day(when, calendar)
        ):
            return Verdict(False, f"us_data_day:{state.name}", state)
        if next_funding_at is not None and self.funding_blackout > timedelta(0):
            gap = abs(require_utc(next_funding_at) - when)
            if gap <= self.funding_blackout:
                return Verdict(False, "funding_settlement", state)
        if symbol is not None:
            ok, why = self.symbol_allowed(state, symbol, rank=rank, screened=screened)
            if not ok:
                return Verdict(False, f"window:{state.name}:{why}", state)
        return Verdict(True, f"window:{state.name}", state)

    def daily_budget_cap(self) -> int:
        """Sum of weekday window budgets; the operator's daily cap may not exceed it."""
        return sum(w.budget for w in self.windows)


def coverage_check(policy: SessionPolicy, day: datetime | None = None) -> int:
    """Every minute of a day resolves to exactly one window. Returns minutes checked."""
    base = require_utc(day) if day is not None else datetime(2026, 1, 5, tzinfo=UTC)
    base = base.replace(hour=0, minute=0, second=0, microsecond=0)
    n = 0
    for minute in range(24 * 60):
        policy.clock_window(base + timedelta(minutes=minute))
        n += 1
    return n
