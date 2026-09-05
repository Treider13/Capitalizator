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


def test_contour_a_does_not_import_xgboost() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator"
    hits: list[str] = []
    model_hits: list[str] = []
    for root in A_ROOTS:
        for path in (src / root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name.split(".")[0] == "xgboost" for alias in node.names):
                        hits.append(str(path.relative_to(src)))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] == "xgboost":
                        hits.append(str(path.relative_to(src)))
                    if "hyexec.model" in node.module:
                        model_hits.append(str(path.relative_to(src)))
                    if any(
                        name in node.module
                        for name in (
                            "hyexec.backfill",
                            "hyexec.replay_desk",
                            "hyexec.import_labels",
                            "hyexec.tape_day",
                        )
                    ):
                        model_hits.append(str(path.relative_to(src)))
    assert hits == []
    assert model_hits == []
    assert (src / "hyexec" / "model.py").is_file()
