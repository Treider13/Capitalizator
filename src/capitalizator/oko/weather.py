"""Weather — which market are we in *right now*, and did it just change.

Adams & MacKay (2007) Bayesian online changepoint detection on log returns of
closed working-TF bars. Normal likelihood with unknown mean and variance
(Normal–Inverse-Gamma prior, Student-t predictive), constant hazard 1/λ.
The run-length posterior is kept exactly up to MAX_RUN and the tail mass is
folded into the last bin. Pure Python, log-space, deterministic.

Prior scale β0 is set once from the first WARMUP returns (empirical Bayes);
until then and until MIN_BARS returns the regime is UNKNOWN — not RANGE.

Regime from the MAP run:
  TRANSITION     P(run ≤ CP_RECENT) ≥ 0.5 — a changepoint in the last bars
  VOL_EXPANSION  run σ ≥ 1.8 × long-run robust σ (≥3 bars in the run)
  TREND          |mean| · √n / σ ≥ 2 inside the run (≥5 bars)
  RANGE          otherwise
Bars closing at or before the last seen close are ignored (replay idempotent).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from capitalizator.types import require_utc
from capitalizator.zones.model import Bar

Regime = Literal["TREND", "RANGE", "VOL_EXPANSION", "TRANSITION", "UNKNOWN"]
REGIMES = frozenset({"TREND", "RANGE", "VOL_EXPANSION", "TRANSITION", "UNKNOWN"})

HAZARD_LAMBDA = 50.0
MAX_RUN = 400
WARMUP = 10
MIN_BARS = 30
CP_RECENT = 2
CP_TRANSITION = 0.5
VOL_EXPANSION_RATIO = 1.8
VOL_MIN_RUN = 3
TREND_T = 2.0
TREND_MIN_RUN = 5
HISTORY = 2000
MU0 = 0.0
KAPPA0 = 1.0
ALPHA0 = 1.0
BETA_FLOOR = 1e-12
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class WeatherReport:
    regime: Regime
    cp_prob: float | None
    run_map: int | None
    run_n: int | None
    run_mean: float | None
    run_sigma: float | None
    long_sigma: float | None
    vol_ratio: float | None
    n_bars: int

    def __post_init__(self) -> None:
        if self.regime not in REGIMES:
            raise ValueError(f"unknown regime: {self.regime!r}")
        if self.cp_prob is not None and not 0.0 <= self.cp_prob <= 1.0 + 1e-9:
            raise ValueError("cp_prob must be in [0, 1]")


@dataclass
class _NIG:
    mu: float
    kappa: float
    alpha: float
    beta: float

    def updated(self, x: float) -> _NIG:
        kappa = self.kappa + 1.0
        mu = (self.kappa * self.mu + x) / kappa
        alpha = self.alpha + 0.5
        beta = self.beta + self.kappa * (x - self.mu) ** 2 / (2.0 * kappa)
        return _NIG(mu=mu, kappa=kappa, alpha=alpha, beta=beta)

    def log_pred(self, x: float) -> float:
        nu = 2.0 * self.alpha
        scale2 = self.beta * (self.kappa + 1.0) / (self.alpha * self.kappa)
        if scale2 <= 0.0:
            scale2 = BETA_FLOOR
        scale = math.sqrt(scale2)
        z = (x - self.mu) / scale
        return (
            math.lgamma((nu + 1.0) / 2.0)
            - math.lgamma(nu / 2.0)
            - 0.5 * math.log(nu * math.pi)
            - math.log(scale)
            - (nu + 1.0) / 2.0 * math.log1p(z * z / nu)
        )


class Weather:
    """One detector per symbol, working TF only. Feed closed bars in close order."""

    def __init__(self, symbol: str, *, tf: str, hazard_lambda: float = HAZARD_LAMBDA) -> None:
        if not symbol or not tf:
            raise ValueError("weather needs symbol and tf")
        if hazard_lambda <= 1.0:
            raise ValueError("hazard_lambda must be > 1")
        self.symbol = symbol
        self.tf = tf
        self.hazard = 1.0 / hazard_lambda
        self.returns: deque[float] = deque(maxlen=HISTORY)
        self.last_close: Decimal | None = None
        self.last_close_ts: datetime | None = None
        self._warm: list[float] = []
        self._prior: _NIG | None = None
        self._log_r: list[float] = []
        self._params: list[_NIG] = []

    @property
    def n(self) -> int:
        return len(self.returns)

    def update(self, bar: Bar) -> float | None:
        """Consume one closed bar. Returns the log return used, or None if skipped."""
        if bar.symbol != self.symbol or bar.tf != self.tf:
            return None
        close_ts = require_utc(bar.close_ts)
        if self.last_close_ts is not None and close_ts <= self.last_close_ts:
            return None
        if bar.close <= 0:
            raise ValueError("bar close must be > 0")
        prev = self.last_close
        self.last_close = bar.close
        self.last_close_ts = close_ts
        if prev is None:
            return None
        x = math.log(float(bar.close) / float(prev))
        self._push(x)
        return x

    def _push(self, x: float) -> None:
        self.returns.append(x)
        if self._prior is None:
            self._warm.append(x)
            if len(self._warm) < WARMUP:
                return
            mean = sum(self._warm) / len(self._warm)
            var = sum((v - mean) ** 2 for v in self._warm) / (len(self._warm) - 1)
            self._prior = _NIG(
                mu=MU0, kappa=KAPPA0, alpha=ALPHA0, beta=max(ALPHA0 * var, BETA_FLOOR)
            )
            self._log_r = [0.0]
            self._params = [self._prior]
            for v in self._warm:
                self._step(v)
            self._warm = []
            return
        self._step(x)

    def _step(self, x: float) -> None:
        assert self._prior is not None
        log_h = math.log(self.hazard)
        log_1h = math.log1p(-self.hazard)
        preds = [p.log_pred(x) for p in self._params]
        joint = [lr + lp for lr, lp in zip(self._log_r, preds, strict=True)]
        growth = [j + log_1h for j in joint]
        cp = _logsumexp([j + log_h for j in joint])
        new_log_r = [cp, *growth]
        new_params = [self._prior, *(p.updated(x) for p in self._params)]
        if len(new_log_r) > MAX_RUN:
            tail = _logsumexp(new_log_r[MAX_RUN - 1 :])
            new_log_r = [*new_log_r[: MAX_RUN - 1], tail]
            new_params = new_params[:MAX_RUN]
        norm = _logsumexp(new_log_r)
        self._log_r = [v - norm for v in new_log_r]
        self._params = new_params

    def report(self) -> WeatherReport:
        n = self.n
        if self._prior is None or not self._log_r:
            return WeatherReport(
                regime="UNKNOWN",
                cp_prob=None,
                run_map=None,
                run_n=None,
                run_mean=None,
                run_sigma=None,
                long_sigma=None,
                vol_ratio=None,
                n_bars=n,
            )
        probs = [math.exp(v) for v in self._log_r]
        cp_prob = min(1.0, sum(probs[: CP_RECENT + 1]))
        run_map = max(range(len(probs)), key=lambda i: (probs[i], -i))
        params = self._params[run_map]
        run_n = int(round(params.kappa - KAPPA0))
        run_mean = params.mu
        run_sigma = math.sqrt(params.beta / (params.alpha - 1.0)) if params.alpha > 1.0 else None
        long_sigma = _robust_sigma(self.returns)
        vol_ratio = (
            run_sigma / long_sigma
            if run_sigma is not None and long_sigma is not None and long_sigma > 0
            else None
        )
        regime: Regime
        if n < MIN_BARS:
            regime = "UNKNOWN"
        elif cp_prob >= CP_TRANSITION:
            regime = "TRANSITION"
        elif vol_ratio is not None and run_n >= VOL_MIN_RUN and vol_ratio >= VOL_EXPANSION_RATIO:
            regime = "VOL_EXPANSION"
        elif (
            run_sigma is not None
            and run_sigma > 0
            and run_n >= TREND_MIN_RUN
            and abs(run_mean) * math.sqrt(run_n) / run_sigma >= TREND_T
        ):
            regime = "TREND"
        else:
            regime = "RANGE"
        return WeatherReport(
            regime=regime,
            cp_prob=cp_prob,
            run_map=run_map,
            run_n=run_n,
            run_mean=run_mean,
            run_sigma=run_sigma,
            long_sigma=long_sigma,
            vol_ratio=vol_ratio,
            n_bars=n,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "tf": self.tf,
            "hazard_lambda": 1.0 / self.hazard,
            "returns": [repr(v) for v in self.returns],
            "last_close": None if self.last_close is None else format(self.last_close, "f"),
            "last_close_ts": (
                None if self.last_close_ts is None else self.last_close_ts.isoformat()
            ),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Weather:
        out = cls(
            str(raw.get("symbol") or ""),
            tf=str(raw.get("tf") or ""),
            hazard_lambda=float(raw.get("hazard_lambda") or HAZARD_LAMBDA),
        )
        returns = raw.get("returns") or []
        if not isinstance(returns, list):
            raise ValueError("weather returns must be a list")
        out.replay(float(v) for v in returns)
        last_close = raw.get("last_close")
        if last_close is not None:
            out.last_close = Decimal(str(last_close))
        last_ts = raw.get("last_close_ts")
        if last_ts is not None:
            out.last_close_ts = require_utc(datetime.fromisoformat(str(last_ts)))
        return out

    def replay(self, returns: Iterable[float]) -> None:
        """Rebuild the posterior from stored log returns. Same order → same state."""
        for x in returns:
            if not math.isfinite(x):
                raise ValueError("returns must be finite")
            self._push(x)


def _logsumexp(values: list[float]) -> float:
    top = max(values)
    if top == -math.inf:
        return -math.inf
    return top + math.log(sum(math.exp(v - top) for v in values))


def _robust_sigma(values: Iterable[float]) -> float | None:
    xs = sorted(values)
    if len(xs) < 2:
        return None
    med = _median(xs)
    mad = _median(sorted(abs(v - med) for v in xs))
    return mad * MAD_TO_SIGMA


def _median(xs: list[float]) -> float:
    n = len(xs)
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0
