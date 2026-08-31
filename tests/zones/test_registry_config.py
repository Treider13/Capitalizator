"""registry.yaml is the PHASE-BUILD freeze. Extra knobs are rejected."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.zones.config import RegistryConfigError, load_registry

REPO = Path(__file__).resolve().parents[2] / "infra" / "registry.yaml"


def test_repo_file_matches_phase_build_keys() -> None:
    cfg = load_registry(REPO)
    assert cfg.working_tf == "15m"
    assert cfg.htf == "4h"
    assert cfg.epsilon_ticks == 2
    assert cfg.bounce_away_ticks == 8
    assert cfg.zlg_window_s == 8
    assert cfg.prs_alpha == 0.7


def test_extra_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(REPO.read_text(encoding="utf-8") + "magic_k: 0.37\n", encoding="utf-8")
    with pytest.raises(RegistryConfigError, match="unknown keys"):
        load_registry(path)
