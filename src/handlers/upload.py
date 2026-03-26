# src/handlers/upload.py
from __future__ import annotations

from . import ConnectionLike


def handle_upload(conn: ConnectionLike, filename: str, size: int) -> None:
    """
    Обработка команды UPLOAD.
    Протокол: команда сообщает имя и размер, затем клиент шлёт size байт.
    """
    raise NotImplementedError("handle_upload is not implemented yet")
