"""Forecast — P(bounce | break | die) for this class, with a conformal set.

Three-level shrinkage on *our* outcomes, no fitted model:

  p_global = (n_y + κ/3) / (n + κ)                  prior: uniform over 3 outcomes
  p_symbol = (n_y + κ·p_global,y) / (n + κ)
  p_class  = (n_y + κ·p_symbol,y) / (n + κ)         class = idea × CAV × ZLG × regime

κ = 20 = N_MIN of the jury: a class with fewer rows than that leans on its
parents and *cannot* be decisive. This is how a new market borrows from the
old ones without pretending it has its own table.

Conformal set (leave-one-out, exact): for every row i in the class the score
s_i = 1 − p_{−i}(y_i) is computed with row i removed from all three levels.
q̂ = the ⌈(n+1)(1−α)⌉-th smallest score, α = 0.2. Prediction set =
{y : 1 − p(y) ≤ q̂}. Marginal coverage ≥ 1−α holds by exchangeability; a set
with two outcomes is an honest "do not know" and gives voice 0.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

OUTCOMES: tuple[str, ...] = ("bounce", "break", "die")
KAPPA = 20.0
N_MIN = 20
ALPHA = 0.2


@dataclass(frozen=True)
class Sample:
    symbol: str
    class_key: str
    outcome: str

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}, got {self.outcome!r}")
        if not self.symbol or not self.class_key:
            raise ValueError("sample needs symbol and class_key")


@dataclass(frozen=True)
class ForecastReport:
    class_key: str
    n_class: int
    n_symbol: int
    n_global: int
    p: Mapping[str, float]
    pred_set: frozenset[str]
    q_hat: float | None
    decisive: str | None

    def __post_init__(self) -> None:
        total = sum(self.p.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError("forecast probabilities must sum to 1")
        if not self.pred_set or not self.pred_set <= set(OUTCOMES):
            raise ValueError("pred_set must be a non-empty subset of OUTCOMES")
        if self.decisive is not None and self.pred_set != frozenset({self.decisive}):
            raise ValueError("decisive must be the singleton pred_set")

    @property
    def set_text(self) -> str:
        return "|".join(sorted(self.pred_set))


def class_key(
    *,
    idea: str,
    cav: str | None,
    zlg: str | None,
    regime: str | None,
    footprint: str | None = None,
) -> str:
    """Forecast class. Missing labels are written as '?', never guessed.

    footprint (INVENTION-OKO §След) is the sixth axis; a row from before the
    organ existed carries '?' and stays in the symbol / global levels.
    """
    if idea not in {"bounce", "spring", "breakout", "failed_break"}:
        raise ValueError("idea must be bounce|spring|breakout|failed_break")
    return f"{idea} × {cav or '?'} × {zlg or '?'} × {regime or '?'} × {footprint or '?'}"


def forecast(
    samples: Iterable[Sample],
    *,
    symbol: str,
    key: str,
    kappa: float = KAPPA,
    alpha: float = ALPHA,
    n_min: int = N_MIN,
) -> ForecastReport:
    if kappa <= 0:
        raise ValueError("kappa must be > 0")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    rows = list(samples)
    g = Counter(s.outcome for s in rows)
    s_ = Counter(s.outcome for s in rows if s.symbol == symbol)
    c = Counter(s.outcome for s in rows if s.symbol == symbol and s.class_key == key)
    p = _chain(g, s_, c, kappa)
    n_class = sum(c.values())
    scores: list[float] = []
    for outcome, count in sorted(c.items()):
        loo = _chain(_minus(g, outcome), _minus(s_, outcome), _minus(c, outcome), kappa)
        scores.extend([1.0 - loo[outcome]] * count)
    q_hat: float | None = None
    if n_class >= n_min:
        q_hat = _quantile(scores, alpha)
        pred = frozenset(y for y in OUTCOMES if 1.0 - p[y] <= q_hat + 1e-12)
        if not pred:
            pred = frozenset(OUTCOMES)
    else:
        pred = frozenset(OUTCOMES)
    decisive = None
    if len(pred) == 1:
        only = next(iter(pred))
        if only in {"bounce", "break"}:
            decisive = only
    return ForecastReport(
        class_key=key,
        n_class=n_class,
        n_symbol=sum(s_.values()),
        n_global=sum(g.values()),
        p=p,
        pred_set=pred,
        q_hat=q_hat,
        decisive=decisive,
    )


def _chain(g: Counter[str], s: Counter[str], c: Counter[str], kappa: float) -> dict[str, float]:
    uniform = {y: 1.0 / len(OUTCOMES) for y in OUTCOMES}
    p_global = _post(g, uniform, kappa)
    p_symbol = _post(s, p_global, kappa)
    return _post(c, p_symbol, kappa)


def _post(counts: Counter[str], parent: Mapping[str, float], kappa: float) -> dict[str, float]:
    n = sum(counts.values())
    return {y: (counts.get(y, 0) + kappa * parent[y]) / (n + kappa) for y in OUTCOMES}


def _minus(counts: Counter[str], outcome: str) -> Counter[str]:
    out = Counter(counts)
    out[outcome] -= 1
    if out[outcome] < 0:
        raise ValueError("cannot remove an outcome that is not counted")
    return out


def _quantile(scores: Sequence[float], alpha: float) -> float:
    """⌈(n+1)(1−α)⌉-th smallest score; 1.0 (everything) if that exceeds n."""
    n = len(scores)
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return 1.0
    return sorted(scores)[k - 1]
