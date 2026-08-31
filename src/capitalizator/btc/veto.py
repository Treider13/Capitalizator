"""2.9.3 — alt vs BTC break. Paper law. Not wired into BounceStrategy.

Long alt after BTC support break → reject.
Short alt after BTC resistance break → reject.
Same direction is not cut. No break → allow.
Does not open size. Does not flip phase.yaml.
"""

from __future__ import annotations

from typing import Literal

Side = Literal["buy", "sell"]
ZoneSide = Literal["support", "resistance"]


class BtcVeto:
    def allow(
        self,
        *,
        alt_side: Side,
        btc_broke: bool,
        btc_zone_side: ZoneSide,
    ) -> bool:
        if not btc_broke:
            return True
        if alt_side == "buy" and btc_zone_side == "support":
            return False
        if alt_side == "sell" and btc_zone_side == "resistance":
            return False
        return True
