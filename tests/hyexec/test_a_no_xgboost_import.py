"""Contour A must not import xgboost. hyexec.model is the only allowed loader."""

from __future__ import annotations

import ast
from pathlib import Path

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


def test_contour_a_does_not_import_xgboost() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator"
    hits: list[str] = []
    for root in A_ROOTS:
        for path in (src / root).rglob("*.py"):
            if "xgboost" in _imports(path):
                hits.append(str(path.relative_to(src)))
    assert hits == []
