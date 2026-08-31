"""0.4.9 — hash chain of zone + gesture + claims. Episode table is empty.

Tampering the gesture of a past link breaks verify().
Does not open size.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import blake2s

GENESIS = "0" * 32


@dataclass(frozen=True)
class HashLink:
    prev_hash: str
    payload: str
    digest: str


class HashChain:
    def __init__(self) -> None:
        self.links: list[HashLink] = []

    def append(self, payload: str) -> HashLink:
        prev = self.links[-1].digest if self.links else GENESIS
        digest = blake2s(f"{prev}|{payload}".encode(), digest_size=16).hexdigest()
        link = HashLink(prev_hash=prev, payload=payload, digest=digest)
        self.links.append(link)
        return link

    def verify(self) -> bool:
        prev = GENESIS
        for link in self.links:
            expect = blake2s(f"{prev}|{link.payload}".encode(), digest_size=16).hexdigest()
            if link.prev_hash != prev or link.digest != expect:
                return False
            prev = link.digest
        return True


def touch_payload(*, zone_id: str, gesture: str, claims: Sequence[str] = ()) -> str:
    return "|".join((zone_id, gesture, *claims))


def episodes() -> list[None]:
    """Phase 0: no fills. Empty on purpose."""
    return []
