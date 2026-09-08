"""Exercise the real deployment shell with isolated Git and Docker commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", ["fetch", "checkout", "pull", "build", ""])
def test_deploy_stops_before_docker_after_git_failure(tmp_path: Path, failure: str) -> None:
    root = tmp_path / "installation"
    app = root / "app"
    (app / ".git").mkdir(parents=True)
    deployment = app / "infra" / "deploy"
    deployment.mkdir(parents=True)
    (deployment / ".env").touch()
    source = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "deploy.sh"
    script = deployment / "deploy.sh"
    script.write_text(source.read_text().replace("DATA=/srv/capitalizator", f'DATA="{root}"'))
    commands = tmp_path / "bin"
    commands.mkdir()
    trace = tmp_path / "trace"
    for name in ("git", "docker"):
        executable = commands / name
        executable.write_text(
            "#!/bin/bash\n"
            f'echo "{name} $*" >> "$DEPLOY_TRACE"\n'
            'if [[ "$1" == "$DEPLOY_FAILURE" || '
            '( "$1" == compose && "${2:-}" == "$DEPLOY_FAILURE" ) ]]; then\n'
            "  exit 23\n"
            "fi\n"
        )
        executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script)],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "CAP_BRANCH": "main",
            "DEPLOY_TRACE": str(trace),
            "DEPLOY_FAILURE": failure,
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = trace.read_text().splitlines()
    expected = [
        "git fetch -q origin",
        "git checkout -q main",
        "git pull -q --ff-only origin main",
        "docker compose build --pull",
        "docker compose up -d --remove-orphans",
        "docker compose ps",
    ]
    stop_at = {"fetch": 1, "checkout": 2, "pull": 3, "build": 4, "": 6}[failure]
    assert calls == expected[:stop_at]
    assert result.returncode == (23 if failure else 0), result.stderr
    assert ("console:" in result.stdout) is (not failure)
