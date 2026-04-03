# src/models/tcp_session.py
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from typing import BinaryIO


@dataclass(slots=True)
class TcpSession:
    sock: socket.socket
    addr: tuple[str, int]

    in_buffer: bytearray = field(default_factory=bytearray)
    out_buffer: bytearray = field(default_factory=bytearray)

    closing: bool = False
    command_mode: str = "line"

    current_file: BinaryIO | None = None
    current_filename: str | None = None
    current_filesize: int = 0
    current_offset: int = 0
    bytes_done: int = 0
    remaining = current_filesize - current_offset - bytes_done

    transfer_kind: str | None = None
    transfer_started_at: float | None = None
    last_progress_step: int = -1


def create_session(
    sock: socket.socket,
    addr: tuple[str, int],
) -> TcpSession:
    """Создать новую клиентскую сессию с начальными буферами и состоянием."""
    return TcpSession(sock=sock, addr=addr)


def reset_transfer_state(session: TcpSession) -> None:
    """
    Сбросить состояние текущей передачи файла.
    Не трогаем сокет, адрес, входной/выходной буферы и флаг closing.
    """
    session.command_mode = "line"

    session.current_filename = None
    session.current_filesize = 0
    session.current_offset = 0
    session.bytes_done = 0

    session.transfer_kind = None
    session.transfer_started_at = None
    session.last_progress_step = -1


def close_session_file(session: TcpSession) -> None:
    """Закрыть открытый файловый дескриптор сессии, если он есть."""
    file_obj = session.current_file
    session.current_file = None

    if file_obj is None:
        return

    try:
        file_obj.close()
    except OSError:
        pass


def start_transfer(
    session: TcpSession,
    *,
    kind: str,
    filename: str,
    filesize: int,
    offset: int = 0,
) -> None:
    """
    Инициализировать метаданные передачи.
    kind: 'upload' или 'download'
    """
    session.transfer_kind = kind
    session.command_mode = kind

    session.current_filename = filename
    session.current_filesize = filesize
    session.current_offset = offset
    session.bytes_done = 0

    session.transfer_started_at = time.perf_counter()
    session.last_progress_step = -1


def mark_session_closing(session: TcpSession) -> None:
    """
    Пометить сессию на закрытие после опустошения out_buffer.
    Если активна передача файла, немедленно сбрасываем файловое состояние.
    """
    session.closing = True
    close_session_file(session)
    reset_transfer_state(session)


def get_transfer_elapsed(session: TcpSession) -> float:
    """Получить длительность текущей передачи в секундах."""
    if session.transfer_started_at is None:
        return 0.0
    return max(0.0, time.perf_counter() - session.transfer_started_at)


def get_transfer_total_done(session: TcpSession) -> int:
    """
    Получить абсолютное количество уже переданных байт файла
    с учетом начального offset.
    """
    return session.current_offset + session.bytes_done