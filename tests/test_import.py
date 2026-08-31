"""−1.1: every package imports; none load keys from the environment."""

from __future__ import annotations

import ast
from pathlib import Path

import capitalizator

PACKAGES = [
    "capitalizator.recorder",
    "capitalizator.book",
    "capitalizator.zones",
    "capitalizator.tape",
    "capitalizator.prs",
    "capitalizator.zlg",
    "capitalizator.btc",
    "capitalizator.screener",
    "capitalizator.card",
    "capitalizator.verifier",
    "capitalizator.authors",
    "capitalizator.news_macro",
    "capitalizator.whales",
    "capitalizator.patterns",
    "capitalizator.llm",
    "capitalizator.risk",
    "capitalizator.signer",
    "capitalizator.memory",
    "capitalizator.champion",
    "capitalizator.exec",
]

SRC = Path(__file__).resolve().parents[1] / "src" / "capitalizator"
FORBIDDEN_ENV_NEEDLES = ("KEY", "SECRET", "TOKEN", "PASS")


def test_root_import() -> None:
    assert capitalizator.__version__


def test_all_packages_import() -> None:
    for name in PACKAGES:
        __import__(name)


def _reads_secret_env(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name not in {"getenv", "environ"} and not (
                isinstance(func, ast.Attribute) and func.attr in {"get", "getenv"}
            ):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    upper = arg.value.upper()
                    if any(needle in upper for needle in FORBIDDEN_ENV_NEEDLES):
                        hits.append(f"{path}:{arg.value}")
    return hits


def test_no_package_loads_keys() -> None:
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        hits.extend(_reads_secret_env(path))
    assert hits == []
