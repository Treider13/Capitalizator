"""Hash chain: swap a gesture → verify() is false. Episode table is empty."""

from __future__ import annotations

from dataclasses import replace

from capitalizator.memory.hashlog import HashChain, episodes, touch_payload


def test_tampered_gesture_breaks_chain() -> None:
    chain = HashChain()
    chain.append(touch_payload(zone_id="z1", gesture="DEFEND"))
    chain.append(touch_payload(zone_id="z1", gesture="RETREAT"))
    assert chain.verify() is True
    broken = HashChain()
    broken.links = list(chain.links)
    broken.links[0] = replace(broken.links[0], payload=touch_payload(zone_id="z1", gesture="FADE"))
    assert broken.verify() is False


def test_two_runs_same_digests() -> None:
    def run() -> list[str]:
        chain = HashChain()
        chain.append(touch_payload(zone_id="z1", gesture="DEFEND"))
        chain.append(touch_payload(zone_id="z1", gesture="SILENCE"))
        return [lnk.digest for lnk in chain.links]

    assert run() == run()


def test_registry_touch_writes_chain() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from capitalizator.memory.registry import Registry
    from capitalizator.types import MarketEvent
    from capitalizator.zones.model import Zone

    zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
    )
    ts = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    reg = Registry(tick_size=Decimal("0.1"))
    reg.on_trade(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=ts,
            recv_ts=ts,
            seq=None,
            payload={"px": "100.1", "qty": "0.001", "side": "buy"},
        ),
        [zone],
    )
    assert len(reg.chain.links) == 1
    assert reg.chain.verify() is True
    first = reg.chain.links[0].digest
    reg.fill_gesture(gesture="DEFEND")
    assert len(reg.chain.links) == 2
    assert reg.chain.links[1].prev_hash == first
    assert reg.chain.verify() is True


def test_episode_table_is_empty() -> None:
    assert episodes() == []
