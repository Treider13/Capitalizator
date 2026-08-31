"""Static scan: src must not read KEY/SECRET/TOKEN/PASS from the environment."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_ENV_NEEDLES = ("KEY", "SECRET", "TOKEN", "PASS")


def _looks_like_secret(value: str) -> bool:
    return any(needle in value.upper() for needle in FORBIDDEN_ENV_NEEDLES)


def _is_environ_get(func: ast.AST) -> bool:
    """os.getenv / os.environ.get / environ.get — not dict.get('amount_tokens')."""
    if isinstance(func, ast.Name) and func.id == "getenv":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "get":
        owner = func.value
        if isinstance(owner, ast.Name) and owner.id == "environ":
            return True
        if isinstance(owner, ast.Attribute) and owner.attr == "environ":
            return True
    return False


def _is_environ_sub(target: ast.AST) -> bool:
    if isinstance(target, ast.Name) and target.id == "environ":
        return True
    return isinstance(target, ast.Attribute) and target.attr == "environ"


def reads_secret_env(source: str, filename: str = "<src>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_environ_get(node.func):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _looks_like_secret(arg.value):
                        hits.append(f"{filename}:{arg.value}")
        if isinstance(node, ast.Subscript) and _is_environ_sub(node.value):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and _looks_like_secret(
                sl.value
            ):
                hits.append(f"{filename}:{sl.value}")
    return hits


def scan_tree(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*.py"):
        hits.extend(reads_secret_env(path.read_text(encoding="utf-8"), str(path)))
    return hits
