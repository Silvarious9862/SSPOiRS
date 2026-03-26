# src/handlers/time_.py
from __future__ import annotations

from . import ConnectionLike


def handle_time(conn: ConnectionLike) -> None:
    """
    Обработка команды TIME.
    Отправляет клиенту текущее время в текстовом виде.
    """
    raise NotImplementedError("handle_time is not implemented yet")
