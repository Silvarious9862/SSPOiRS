# src/handlers/echo.py
from __future__ import annotations

from . import ConnectionLike


def handle_echo(conn: ConnectionLike, args: str) -> None:
    """
    Обработка команды ECHO.
    args — строка после имени команды.
    """
    raise NotImplementedError("handle_echo is not implemented yet")
