"""Long research pauses must outlive the bounded display history."""

from tests.fusion.test_contract_runtime import block, contract, instrument
from tests.fusion.test_liquidation_pressure import Feed

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.pressure_research import ResearchEngine
from capitalizator.fusion.store import Store


def test_long_pause_survives_twenty_opposite_episodes(tmp_path, monkeypatch):
    source = Store(tmp_path / "pause.sqlite3")
    try:
        feed = Feed()
        feed.warm()
        engine = ResearchEngine(
            "BTCUSDT", source, Shared(), Config(), research_policy="pause", pause_s=10000
        )
        engine.pressure = feed.observer
        engine.market = feed.market
        original = feed.event

        def event(kind, body, at=None):
            result = original(kind, body, at)
            # Deliver the observed state through the research hook as in replay.
            engine._observe(kind, body, feed.at if at is None else at, feed.ident)
            return result

        feed.event = event
        feed.wave()
        first_wave = feed.observer.episodes["sell"].last_wave
        for _ in range(120):
            feed.second(99.5)
        assert not feed.observer.episodes
        feed.direction = "buy"
        for _ in range(21):
            for _ in range(30):
                feed.second(100, sell_qty=2, buy_qty=1)
            feed.wave()
            for _ in range(120):
                feed.second(100.5, sell_qty=2, buy_qty=1)
            assert not feed.observer.episodes
        assert len(feed.observer.history) == 20
        assert all(e["direction"] == "buy" for e in feed.observer.history)
        assert feed.at - first_wave < 10000
        engine.contract = contract()
        sent = []
        monkeypatch.setattr(Engine, "_send", lambda *args: sent.append(True))
        engine._send(block(at=feed.at + 0.5), None, instrument(), "demo", True, 0)
        assert not sent
        # The independent memory must still expire by time, not become a permanent veto.
        while feed.at < first_wave + 10120:
            feed.second(100.5, sell_qty=2, buy_qty=1)
        engine._send(block(at=feed.at + 0.5), None, instrument(), "demo", True, 0)
        assert sent == [True]
    finally:
        source.close()
