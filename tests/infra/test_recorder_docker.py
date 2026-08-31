"""0.1.3 files exist and do not smuggle keys. No docker daemon required."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "infra" / "recorder" / "Dockerfile"
COMPOSE = ROOT / "infra" / "recorder" / "compose.yml"


def test_dockerfile_is_recorder_only() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "capitalizator.recorder.app" in text
    assert "--serve" in text
    assert "COPY src" in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        upper = stripped.upper()
        assert "SIGNER" not in upper
        assert ".ENV" not in upper
        assert "API_KEY" not in upper
        assert not stripped.upper().startswith("ENV ") or "KEY" not in upper


def test_compose_has_no_env_file() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "8081" in text
    assert "/healthz" in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        assert not stripped.startswith("env_file:")
