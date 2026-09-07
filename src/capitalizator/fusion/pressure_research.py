"""Offline full-strategy comparison. Never imported by the live runtime.

Three independent simulated accounts share the recorded receipt stream and the
same causal learning settings. A common observation warmup avoids attributing
warmup abstention to pressure detection. Results are not live execution evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any

from capitalizator.fusion.archive import events
from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine
from capitalizator.fusion.liquidation_pressure import PressureConfig
from capitalizator.fusion.market import Block
from capitalizator.fusion.pressure_labels import label_episodes
from capitalizator.fusion.replay import compare
from capitalizator.fusion.risk import Instrument
from capitalizator.fusion.store import Store


class ResearchEngine(Engine):
    """Veto only before the normal reserve/send path, in ReplayVenue exclusively."""

    def __init__(self, *args: Any, research_policy: str, pause_s: float = 120, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if research_policy not in {"baseline", "pause", "detector"}:
            raise ValueError("unknown research policy")
        self.research_policy, self.pause_s = research_policy, pause_s
        self.pause_waves: dict[str, float] = {}

    def _observe(self, kind: str, frame: dict[str, Any], at: float, event_id: int) -> None:
        super()._observe(kind, frame, at, event_id)
        # Two causal timestamps suffice; display-history eviction cannot end a pause.
        for episode in self.pressure.episodes.values():
            self.pause_waves[episode.direction] = max(
                self.pause_waves.get(episode.direction, -float("inf")), episode.last_wave
            )

    def _send(
        self,
        block: Block,
        forecast: Any,
        instrument: Instrument | None,
        mode: str,
        allow: bool,
        cost: float,
    ) -> None:
        state = self.pressure_snapshot(block.at)
        assert self.contract is not None
        side = "Buy" if self.contract.side == 1 else "Sell"
        direction = "sell" if side == "Buy" else "buy"
        reason = None
        if state["quality"] != "ready":
            reason = "common_observation_not_ready"
        elif self.research_policy == "detector" and side in state["would_block"]:
            reason = "pressure_detector"
        elif self.research_policy == "pause":
            for episode in [*state["episodes"], *state["recent_episodes"]]:
                self.pause_waves[episode["direction"]] = max(
                    self.pause_waves.get(episode["direction"], -float("inf")),
                    episode["last_wave"],
                )
            last_wave = self.pause_waves.get(direction)
            if last_wave is not None and 0 <= block.at - last_wave < self.pause_s:
                reason = "fixed_pause"
        self.store.decision(
            block.at,
            self.symbol,
            "pressure_research_decision",
            {
                "policy": self.research_policy,
                "contract": self.contract.id,
                "side": side,
                "would_veto": reason,
                "pause_last_wave": (
                    self.pause_waves.get(direction) if self.research_policy == "pause" else None
                ),
                "pressure": state,
                "scope": "offline simulated account only",
            },
        )
        if reason is None:
            super()._send(block, forecast, instrument, mode, allow, cost)


def run(
    source: Store,
    root: Path,
    output: Path,
    config: Config,
    instruments: dict[str, Instrument],
    pressure_config: PressureConfig,
    *,
    latency: float = 0.2,
    pause_s: float = 120,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("research output must be a new directory")
    if pressure_config.mode != "observe" or set(config.symbols) - set(pressure_config.symbols):
        raise ValueError("research requires observation enabled for every selected symbol")
    if not 0 < pause_s < float("inf"):
        raise ValueError("invalid pause")
    output.mkdir(parents=True)
    frozen = Store(output / "input.sqlite3")
    digest = hashlib.sha256()
    event_count = 0
    try:
        with frozen.transaction() as db:
            for event in events(source, root):
                digest.update(json.dumps(event, sort_keys=True).encode())
                db.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?)",
                    (event["id"], event["received"], event["symbol"], event["kind"], event["body"]),
                )
                event_count += 1
        results = {}
        for policy in ("baseline", "pause", "detector"):
            results[policy] = compare(
                frozen,
                output,
                output / policy,
                config,
                instruments,
                latency=latency,
                pressure_config=pressure_config,
                variants=("D",),
                engine_factory=partial(ResearchEngine, research_policy=policy, pause_s=pause_s),
            )["D"]
    finally:
        frozen.close()
    baseline = Store(output / "baseline" / "D.sqlite3")
    frozen = Store(output / "input.sqlite3")
    try:
        labels = label_episodes(
            frozen,
            output,
            baseline.rows(
                "SELECT * FROM decisions WHERE kind='pressure_observation' ORDER BY at,id"
            ),
            instruments,
            max_age_s=pressure_config.max_age_s,
        )
    finally:
        baseline.close()
        frozen.close()
    (output / "episode-labels.json").write_text(json.dumps(labels, indent=2, allow_nan=False))
    counts = {}
    for policy in results:
        db = Store(output / policy / "D.sqlite3")
        try:
            counts[policy] = {
                "observations": db.rows(
                    "SELECT count(*) n FROM decisions WHERE kind='pressure_observation'"
                )[0]["n"],
                "decisions": db.rows(
                    "SELECT count(*) n FROM decisions WHERE kind='pressure_research_decision'"
                )[0]["n"],
                "ready_decisions": db.rows(
                    "SELECT count(*) n FROM decisions WHERE kind='pressure_research_decision' "
                    "AND json_extract(body,'$.pressure.quality')='ready'"
                )[0]["n"],
                "vetoes": db.rows(
                    "SELECT count(*) n FROM decisions WHERE kind='pressure_research_decision' "
                    "AND json_extract(body,'$.would_veto') IS NOT NULL"
                )[0]["n"],
                "recorded_fills": db.rows("SELECT count(*) n FROM executions")[0]["n"],
            }
        finally:
            db.close()
    evaluable = all(v["ready_decisions"] and v["recorded_fills"] for v in counts.values())
    result = {
        "status": "descriptive_only" if evaluable else "insufficient_evidence",
        "study_version": "pressure-study-3",
        "reproduction": {
            "config": asdict(config),
            "pressure_config": asdict(pressure_config),
            "instruments": {symbol: asdict(value) for symbol, value in instruments.items()},
            "label_version": labels["label_version"],
        },
        "input_events": event_count,
        "episode_catalog": "episode-labels.json",
        "distinct_episodes": labels["distinct_episodes"],
        "input_sha256": digest.hexdigest(),
        "pressure_version": pressure_config.version,
        "policy_version": config.version,
        "latency_s": latency,
        "pause_s": pause_s,
        "counts": counts,
        "results": results,
        "promotion_allowed": False,
        "limitations": [
            "thresholds must be frozen before a separate chronological holdout",
            "a common readiness gate applies to all three research arms",
            "historical replay assumes small orders and cannot prove live queue position or impact",
            "no fills or no qualified decisions is insufficient evidence",
            "descriptive comparison has no automatic significance or Live promotion claim",
            "liquidation feed coverage and independent episode count require external review",
        ],
    }
    (output / "pressure-comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--userdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pressure-config", type=Path)
    parser.add_argument("--instruments", type=Path)
    parser.add_argument("--latency", type=float, default=0.2)
    parser.add_argument("--pause", type=float, default=120)
    args = parser.parse_args()
    config = Config.load(args.config)
    pressure = PressureConfig.load(
        args.pressure_config or args.userdir / "liquidation_pressure.json"
    )
    path = args.userdir / "fusion.sqlite3"
    if not path.is_file():
        parser.error("existing recorded userdir is required")
    source = Store(path)
    try:
        rows = (
            json.loads(args.instruments.read_text())
            if args.instruments
            else source.meta("instruments:demo", {})
        )
        instruments = {s: Instrument(**v) for s, v in rows.items()}
        if set(config.symbols) - instruments.keys():
            parser.error("recorded instrument metadata required")
        result = run(
            source,
            args.userdir,
            args.output,
            config,
            instruments,
            pressure,
            latency=args.latency,
            pause_s=args.pause,
        )
        print(json.dumps(result, indent=2))
    finally:
        source.close()


if __name__ == "__main__":
    main()
