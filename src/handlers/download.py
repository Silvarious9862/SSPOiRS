# src/handlers/download.py
from __future__ import annotations

from . import ConnectionLike


def handle_download(conn: ConnectionLike, filename: str) -> None:
    """
    Обработка команды DOWNLOAD.
    Сервер читает файл и отправляет размер + содержимое.
    """
    raise NotImplementedError("handle_download is not implemented yet")
