"""Workflow file is real YAML. GitHub Actions startup is a host fact, not this file."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "lint.yml"


def test_lint_workflow_has_ruff_and_pytest() -> None:
    raw = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert raw["name"] == "lint"
    steps = [step.get("name") for step in raw["jobs"]["lint"]["steps"]]
    assert "Ruff" in steps
    assert "Tests" in steps
    runs = "\n".join(step.get("run", "") for step in raw["jobs"]["lint"]["steps"])
    assert "ruff check src tests" in runs
    assert "pytest" in runs
    assert "pip install -e \".[dev]\"" in runs
