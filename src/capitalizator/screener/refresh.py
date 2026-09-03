"""Daily universe proposal: top-10 linear USDT perps by 24h turnover, by rule.

Rule:
  * candidates = instruments-info rows with status Trading, linear USDT perpetual;
  * history ≥ `history_min_days` on Bybit (`launchTime` from instruments-info);
  * ranked by `turnover24h` from /v5/market/tickers; majors are always included;
  * the top `size` (10) fill the list; a current alt may stay if it is still
    inside `size + hysteresis` (default 12) so a one-day rank wobble does not
    churn the tape;
  * symbols that fall out are reported with the reason.

The proposal is written to knowledge meta `universe_proposal`. The signer
applies it the same day (`publish_and_apply`); a human can still ack through
the console. Either path rewrites the applied `universe.yaml` and is hot:
the recorder resubscribes, `load_desk_universe()` sees the new file, no restart.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from capitalizator.ops.knowledge import Knowledge
from capitalizator.screener.universe import (
    MAX_SYMBOLS,
    REQUIRED_SYMBOLS,
    Universe,
    applied_universe_path,
    default_desk_path,
    load_universe,
    validate_universe,
)
from capitalizator.types import require_utc

META_PROPOSAL = "universe_proposal"
META_APPLIED = "universe_applied"
DEFAULT_SIZE = 10
HISTORY_MIN_DAYS = 30
REFRESH_S = 24 * 3600
HYSTERESIS = 2  # keep a current alt if still in top (size + this)


@dataclass(frozen=True)
class Candidate:
    symbol: str
    turnover24h: Decimal
    launched_at: datetime | None
    status: str


@dataclass(frozen=True)
class UniverseProposal:
    at: datetime
    size: int
    symbols: tuple[str, ...]
    ranked: tuple[tuple[str, str], ...]  # (symbol, turnover24h) in rank order
    added: tuple[str, ...]
    dropped: tuple[str, ...]
    rejected: dict[str, str] = field(default_factory=dict)  # symbol → why not a candidate
    current: tuple[str, ...] = ()
    hysteresis: int = 0

    @property
    def proposal_id(self) -> str:
        from hashlib import blake2s

        body = json.dumps(
            {"at": self.at.isoformat(), "symbols": list(self.symbols)}, sort_keys=True
        )
        return blake2s(body.encode(), digest_size=8).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "at": self.at.isoformat(),
            "size": self.size,
            "symbols": list(self.symbols),
            "ranked": [{"symbol": s, "turnover24h": t} for s, t in self.ranked],
            "added": list(self.added),
            "dropped": list(self.dropped),
            "rejected": dict(sorted(self.rejected.items())),
            "current": list(self.current),
            "changes": bool(self.added or self.dropped),
            "takes_effect": "hot",
            "hysteresis": self.hysteresis,
        }


def _launch(row: Mapping[str, Any]) -> datetime | None:
    raw = row.get("launchTime")
    if raw in (None, "", "0", 0):
        return None
    try:
        return datetime.fromtimestamp(int(str(raw)) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def candidates(
    instruments: Iterable[Mapping[str, Any]],
    tickers: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Candidate], dict[str, str]]:
    """Join instruments-info with tickers. Returns (candidates, rejected-with-reason)."""
    turnover: dict[str, Decimal] = {}
    for t in tickers:
        sym = str(t.get("symbol") or "")
        raw = t.get("turnover24h")
        if not sym or raw in (None, ""):
            continue
        try:
            turnover[sym] = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            continue
    out: dict[str, Candidate] = {}
    rejected: dict[str, str] = {}
    for row in instruments:
        sym = str(row.get("symbol") or "")
        if not sym:
            continue
        if str(row.get("contractType") or "LinearPerpetual") != "LinearPerpetual":
            rejected[sym] = "not_perpetual"
            continue
        if str(row.get("quoteCoin") or "USDT") != "USDT" or not sym.endswith("USDT"):
            rejected[sym] = "not_usdt"
            continue
        status = str(row.get("status") or "")
        if status != "Trading":
            rejected[sym] = f"status:{status or 'unknown'}"
            continue
        if sym not in turnover:
            rejected[sym] = "no_ticker"
            continue
        out[sym] = Candidate(
            symbol=sym, turnover24h=turnover[sym], launched_at=_launch(row), status=status
        )
    return out, rejected


def propose(
    *,
    now: datetime,
    instruments: Iterable[Mapping[str, Any]],
    tickers: Iterable[Mapping[str, Any]],
    current: Universe,
    size: int = DEFAULT_SIZE,
    history_min_days: int = HISTORY_MIN_DAYS,
    majors: Iterable[str] = REQUIRED_SYMBOLS,
    hysteresis: int = HYSTERESIS,
) -> UniverseProposal:
    when = require_utc(now)
    if not (2 <= size <= MAX_SYMBOLS):
        raise ValueError(f"size must be in [2, {MAX_SYMBOLS}]")
    if hysteresis < 0:
        raise ValueError("hysteresis must be >= 0")
    pool, rejected = candidates(instruments, tickers)
    majors_t = tuple(majors)
    for m in majors_t:
        if m not in pool:
            raise ValueError(f"major {m} is not a tradable candidate: {rejected.get(m, 'absent')}")
    min_age = timedelta(days=history_min_days)
    eligible: list[Candidate] = []
    for c in pool.values():
        if c.symbol in majors_t:
            eligible.append(c)
            continue
        if c.launched_at is None:
            rejected[c.symbol] = "no_launch_time"
            continue
        if when - c.launched_at < min_age:
            rejected[c.symbol] = f"history<{history_min_days}d"
            continue
        eligible.append(c)
    ranked = sorted(eligible, key=lambda c: (-c.turnover24h, c.symbol))
    rank_of = {c.symbol: i + 1 for i, c in enumerate(ranked)}
    cutoff = size + hysteresis
    chosen: list[str] = list(majors_t)
    current_alts = [s for s in current.symbols if s not in majors_t]
    current_alts.sort(key=lambda s: (rank_of.get(s, 10**9), s))
    for symbol in current_alts:
        if symbol not in pool:
            continue
        if rank_of.get(symbol, 10**9) <= cutoff and len(chosen) < size:
            chosen.append(symbol)
    for c in ranked:
        if len(chosen) >= size:
            break
        if c.symbol not in chosen:
            chosen.append(c.symbol)
    symbols = tuple(chosen)
    cur = set(current.symbols)
    new = set(symbols)
    for sym in sorted(cur - new):
        rejected.setdefault(sym, "rank_below_cut")
    return UniverseProposal(
        at=when,
        size=size,
        symbols=symbols,
        ranked=tuple((c.symbol, str(c.turnover24h)) for c in ranked),
        added=tuple(sorted(new - cur)),
        dropped=tuple(sorted(cur - new)),
        rejected={k: v for k, v in rejected.items() if k in cur or k in new},
        current=tuple(current.symbols),
        hysteresis=hysteresis,
    )


def publish_proposal(
    knowledge: Knowledge,
    *,
    now: datetime,
    instruments: Iterable[Mapping[str, Any]],
    tickers: Iterable[Mapping[str, Any]],
    universe_path: Path | None = None,
    size: int = DEFAULT_SIZE,
    hysteresis: int = HYSTERESIS,
) -> UniverseProposal:
    current = load_universe(universe_path or default_desk_path())
    proposal = propose(
        now=now,
        instruments=instruments,
        tickers=tickers,
        current=current,
        size=size,
        hysteresis=hysteresis,
    )
    knowledge.set_meta(META_PROPOSAL, json.dumps(proposal.to_payload(), sort_keys=True))
    return proposal


def publish_and_apply(
    knowledge: Knowledge,
    *,
    now: datetime,
    instruments: Iterable[Mapping[str, Any]],
    tickers: Iterable[Mapping[str, Any]],
    universe_path: Path | None = None,
    size: int = DEFAULT_SIZE,
    hysteresis: int = HYSTERESIS,
) -> UniverseProposal:
    """Daily path: propose and apply in one step. The file change is hot."""
    proposal = publish_proposal(
        knowledge,
        now=now,
        instruments=instruments,
        tickers=tickers,
        universe_path=universe_path,
        size=size,
        hysteresis=hysteresis,
    )
    apply_universe(
        knowledge,
        proposal_id=proposal.proposal_id,
        ack=True,
        now=now,
        universe_path=universe_path,
    )
    return proposal


def apply_universe(
    knowledge: Knowledge,
    *,
    proposal_id: str,
    ack: bool,
    now: datetime,
    universe_path: Path | None = None,
) -> Universe:
    """Rewrite the applied universe.yaml from the stored proposal. Validated, chained.

    Hot: the next `load_desk_universe()` and the recorder's `set_symbols` see
    the new list. No process restart.
    """
    if not ack:
        raise ValueError("ack required to change the universe")
    raw = knowledge.meta(META_PROPOSAL)
    if not raw:
        raise ValueError("no universe proposal stored")
    payload = json.loads(raw)
    if payload.get("proposal_id") != proposal_id:
        raise ValueError("proposal_id does not match the stored proposal")
    body = {
        "exchange": "bybit",
        "category": "linear",
        "symbols": list(payload["symbols"]),
    }
    universe = validate_universe(body)
    target = universe_path or applied_universe_path() or default_desk_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "# Written by screener.refresh.apply_universe (top-N by 24h turnover, "
        f"history ≥ {HISTORY_MIN_DAYS}d, majors always). proposal_id={proposal_id}\n"
        f"# applied_at={require_utc(now).isoformat()}\n"
        + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    )
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    knowledge.set_meta(
        META_APPLIED,
        json.dumps(
            {
                "proposal_id": proposal_id,
                "at": require_utc(now).isoformat(),
                "symbols": list(universe.symbols),
            },
            sort_keys=True,
        ),
    )
    knowledge.append_link(
        json.dumps(
            {"k": "universe", "proposal_id": proposal_id, "n": len(universe.symbols)},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return universe
