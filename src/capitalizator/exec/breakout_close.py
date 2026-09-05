"""3.13.2 paper — close beyond + eaten + BTC same side. Flag off → no.

Wick without close is not a breakout. First minute is reject.
Does not emit an Intent. Does not import signer. Flag stays false in F0–F2.
"""

from __future__ import annotations

from decimal import Decimal

CHASE_SIZE = Decimal("0.40")
RETEST_SIZE = Decimal("1")


def breakout_size(*, retest: bool) -> Decimal:
    """Retest keeps full size. Flow without a retest is a chase at 0.40."""
    return RETEST_SIZE if retest else CHASE_SIZE


class BreakoutClose:
    @staticmethod
    def allow(
        *,
        enabled: bool,
        close_beyond: bool,
        tape_eaten: bool,
        btc_same: bool,
        first_minute: bool,
    ) -> bool:
        if not enabled:
            return False
        if first_minute:
            return False
        return close_beyond and tape_eaten and btc_same
