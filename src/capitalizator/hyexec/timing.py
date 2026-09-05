"""5m timing. The book prints the ticket. The model may wait. It never invents."""

from __future__ import annotations


def may_send(*, book_ticket: bool, model_go: bool | None) -> bool:
    if not book_ticket:
        return False
    if model_go is None:
        return True
    return model_go
