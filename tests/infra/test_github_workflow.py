"""Workflow file is real YAML. GitHub Actions startup is a host fact, not this file."""

from __future__ import annotations

import shlex
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
    installs = [shlex.split(line) for line in runs.splitlines() if line.startswith("pip install ")]
    assert len(installs) == 1
    install = installs[0]
    assert install[install.index("-c") + 1] == "requirements.lock"
    editable = install[install.index("-e") + 1]
    assert editable.startswith(".[") and editable.endswith("]")
    assert set(editable[2:-1].split(",")) >= {"dev", "live", "hyexec", "talib"}
    assert "pip check" in runs.splitlines()
