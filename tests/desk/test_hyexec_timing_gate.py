"""Model may delay a printed book. It cannot invent a ticket."""

from __future__ import annotations

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
