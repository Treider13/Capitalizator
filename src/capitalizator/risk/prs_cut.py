"""2.10.3 — thin book (Y above a passed threshold) skips. No order to measure.

Threshold is an argument, not a new registry.yaml key (that file is frozen).
Y is None when PRS has <30 X — that is unmeasured, not a fake thin book.
"""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.schema import RiskDecision


def decide(y: Decimal | None, *, threshold: Decimal) -> RiskDecision:
    if threshold <= 0:
        raise ValueError("prs threshold must be > 0")
    if y is None:
        return RiskDecision(action="accept", reason="prs_unmeasured")
    if y > threshold:
        return RiskDecision(action="reject", reason="prs_thin")
    return RiskDecision(action="accept", reason="prs_ok")
