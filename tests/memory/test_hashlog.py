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


def test_episode_table_is_empty() -> None:
    assert episodes() == []
