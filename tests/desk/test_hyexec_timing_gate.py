"""Model may delay a printed book. It cannot invent a ticket."""

from __future__ import annotations

import json
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_no_model_means_book_alone_may_send(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
    assert desk.hyexec_model_go is None
    assert desk.allow_hyexec_send(book_ticket=True) is True
    assert desk.allow_hyexec_send(book_ticket=False) is False


def test_model_hold_blocks_even_when_book_printed(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
    desk.hyexec_model_go = False
    assert desk.allow_hyexec_send(book_ticket=True) is False


def test_model_go_without_book_is_still_not_a_ticket(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
    desk.hyexec_model_go = True
    assert desk.allow_hyexec_send(book_ticket=False) is False


def test_desk_reads_serve_hold_from_meta(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "d"))
    knowledge.set_meta("hyexec_serve", json.dumps({"model_go": False}))
    desk = DeskLoop(knowledge=knowledge, user_mode="off")
    assert desk.allow_hyexec_send(book_ticket=True) is False


def test_desk_reads_serve_none_as_book_alone(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "d"))
    knowledge.set_meta("hyexec_serve", json.dumps({"model_go": None}))
    desk = DeskLoop(knowledge=knowledge, user_mode="off")
    assert desk.allow_hyexec_send(book_ticket=True) is True


def test_desk_uses_per_symbol_serve_score(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "d"))
    knowledge.set_meta(
        "hyexec_serve",
        json.dumps(
            {
                "model_go": False,
                "by_symbol": {
                    "ETHUSDT": {"model_go": False, "score": -0.4},
                    "BTCUSDT": {"model_go": True, "score": 1.2},
                },
            }
        ),
    )
    desk = DeskLoop(knowledge=knowledge, user_mode="off")
    assert desk.allow_hyexec_send(book_ticket=True, symbol="ETHUSDT") is False
    assert desk.allow_hyexec_send(book_ticket=True, symbol="BTCUSDT") is True


def test_missing_symbol_score_is_book_alone_not_global_hold(tmp_path: Path) -> None:
    """A hold on ETH is not a hold on BTC. Global model_go was the last print."""
    knowledge = open_knowledge(init_vault(tmp_path / "d"))
    knowledge.set_meta(
        "hyexec_serve",
        json.dumps(
            {
                "model_go": False,
                "by_symbol": {"ETHUSDT": {"model_go": False, "score": -0.4}},
            }
        ),
    )
    desk = DeskLoop(knowledge=knowledge, user_mode="off")
    assert desk.allow_hyexec_send(book_ticket=True, symbol="ETHUSDT") is False
    assert desk.allow_hyexec_send(book_ticket=True, symbol="BTCUSDT") is True
