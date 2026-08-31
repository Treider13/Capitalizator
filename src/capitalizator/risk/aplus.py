"""5.23 paper — A+ is five roles yes AND BTC same side. F1 cannot raise lev.

Does not change infra/phase.yaml max_lev. Does not open night 5x.
"""

from __future__ import annotations

from collections.abc import Sequence


class APlus:
    @staticmethod
    def ok(*, roles: Sequence[bool], btc_same: bool) -> bool:
        return len(roles) == 5 and all(roles) and btc_same

    @staticmethod
    def raises_lev_in_f1() -> bool:
        return False
