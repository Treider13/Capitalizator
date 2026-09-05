"""hyexec processes are declared. The desk stays network_mode none. Train is not A."""

from __future__ import annotations

from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "compose.yml"


def test_desk_still_has_no_network() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    desk = text.split("desk:")[1].split("signer:")[0]
    assert "network_mode: none" in desk


def test_hyexec_and_train_are_separate_services() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "capitalizator.hyexec.serve" in text
    assert "capitalizator.hyexec.train" in text
    hyexec = text.split("  hyexec:")[1].split("  hyexec-train:")[0]
    assert "network_mode: none" in hyexec
    train = text.split("  hyexec-train:")[1]
    assert "network_mode: none" in train
    assert 'restart: "no"' in train
    assert "capitalizator.desk" not in hyexec


def test_image_installs_hyexec_extra() -> None:
    text = (Path(__file__).resolve().parents[2] / "infra" / "deploy" / "Dockerfile").read_text()
    assert ".[live,hyexec]" in text
    assert "libgomp1" in text


def test_serve_does_not_import_xgboost() -> None:
    import ast

    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "hyexec" / "serve.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    assert "xgboost" not in names
