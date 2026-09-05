"""ADWIN is river's (online-ml/river), not a homemade detector. Contour A stays clean."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from capitalizator.hyexec.adwin import should_retrain

A_ROOTS = (
    "desk",
    "exec",
    "jury",
    "zones",
    "tape",
    "book",
    "risk",
    "signer",
    "gateway",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return names


def test_contour_a_does_not_import_river() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator"
    hits: list[str] = []
    for root in A_ROOTS:
        for path in (src / root).rglob("*.py"):
            names = _imports(path)
            if "river" in names or "river_adwin" in path.name:
                if "river" in names:
                    hits.append(str(path.relative_to(src)))
    assert hits == []
    adwin = src / "hyexec" / "adwin.py"
    assert "river" not in _imports(adwin)


def test_size_cut_flag_does_not_need_river() -> None:
    assert should_retrain(adwin_drift=False) is False
    assert should_retrain(adwin_drift=True) is True


def test_river_adwin_flags_a_mean_shift() -> None:
    pytest.importorskip("river")
    from capitalizator.hyexec.river_adwin import drift_on

    stable = [0.0] * 80
    assert drift_on(stable) is False
    shifted = stable + [1.0] * 80
    assert drift_on(shifted) is True
