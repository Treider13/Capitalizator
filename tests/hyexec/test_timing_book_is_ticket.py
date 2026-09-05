"""Model times a printed book ticket. It never invents an entry."""

from __future__ import annotations

from capitalizator.hyexec.timing import may_send


def test_model_go_without_book_is_not_a_ticket() -> None:
    assert may_send(book_ticket=False, model_go=True) is False


def test_book_ticket_waits_when_model_says_hold() -> None:
    assert may_send(book_ticket=True, model_go=False) is False


def test_book_ticket_sends_when_model_goes() -> None:
    assert may_send(book_ticket=True, model_go=True) is True


def test_no_model_means_book_alone() -> None:
    """Contour A today: no hyexec model loaded. A printed book still sends."""
    assert may_send(book_ticket=True, model_go=None) is True
    assert may_send(book_ticket=False, model_go=None) is False
