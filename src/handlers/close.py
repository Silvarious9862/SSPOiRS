# src/handlers/close.py
from __future__ import annotations

from . import ConnectionLike


def handle_close(conn: ConnectionLike) -> None:
    """
    Обработка команды CLOSE/EXIT/QUIT.
    Может отправить подтверждение и закрыть соединение.
    """
    raise NotImplementedError("handle_close is not implemented yet")
