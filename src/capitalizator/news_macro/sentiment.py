"""2.12.5 — monthly extreme greed is de-risk. Hourly 'buy fear' is reject.

Does not invent a fear/greed print. The caller already measured the window.
Does not open a short because 'everyone bought'.
"""

from __future__ import annotations

from capitalizator.risk.schema import RiskDecision


def decide(*, window: str, extreme_greed: bool) -> RiskDecision:
    if window != "month":
        return RiskDecision(action="reject", reason="sentiment_not_month")
    if extreme_greed:
        return RiskDecision(action="reject", reason="monthly_greed")
    return RiskDecision(action="accept", reason="sentiment_ok")
