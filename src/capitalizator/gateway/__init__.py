"""Bybit v5 gateway — the only package that holds an API key or imports pybit.

Desk never imports this. The signer process builds a BybitGateway when keys exist
and hands `gateway.send` to the queue drain; without keys the drain keeps the
honest `{"status": "not_sent"}` stub and the console says so.
"""

from capitalizator.gateway.bybit import BybitGateway, GatewayError, order_link_id
from capitalizator.gateway.keys import Keys, load_keys
from capitalizator.gateway.tracker import PositionSnapshot, PositionTracker
from capitalizator.gateway.watchdog import Watchdog

__all__ = [
    "BybitGateway",
    "GatewayError",
    "Keys",
    "PositionSnapshot",
    "PositionTracker",
    "Watchdog",
    "load_keys",
    "order_link_id",
]
