"""−1.1: every package imports; none load keys from the environment."""

from __future__ import annotations

from pathlib import Path

import capitalizator
from capitalizator.recorder.scan_keys import reads_secret_env, scan_tree

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
    "capitalizator.jury",
    "capitalizator.llm",
    "capitalizator.risk",
    "capitalizator.signer",
    "capitalizator.memory",
    "capitalizator.champion",
    "capitalizator.exec",
    "capitalizator.storage",
]

SRC = Path(__file__).resolve().parents[1] / "src" / "capitalizator"


def test_root_import() -> None:
    assert capitalizator.__version__


def test_all_packages_import() -> None:
    for name in PACKAGES:
        __import__(name)


def test_scanner_catches_environ_subscript() -> None:
    src = "import os\nvalue = os.environ['BYBIT_API_KEY']\n"
    assert reads_secret_env(src, "snippet.py")


def test_scanner_catches_getenv() -> None:
    src = "import os\nvalue = os.getenv('API_SECRET')\n"
    assert reads_secret_env(src, "snippet.py")


def test_dict_get_amount_tokens_is_not_an_env_key() -> None:
    src = 'row = {"amount_tokens": "1"}\nvalue = row.get("amount_tokens")\n'
    assert reads_secret_env(src, "snippet.py") == []


def test_no_package_loads_keys() -> None:
    assert scan_tree(SRC) == []
