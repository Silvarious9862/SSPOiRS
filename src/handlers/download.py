# src/handlers/download.py
from __future__ import annotations

import os
import time
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize


BUFFER_SIZE: Final[int] = 4096
BASE_DIR: Final[str] = "server_files"

UPLOAD_DELAY_PER_CHUNK = 0.05  # 50 ms после каждого recv
DOWNLOAD_DELAY_PER_CHUNK = 0.05  # 50 ms после каждого send


def is_download_command(request: str) -> bool:
    return request.upper().startswith("DOWNLOAD")


def parse_download_command(request: str) -> tuple[str, int] | None:
    """
    Ожидаем:
      DOWNLOAD <filename>
    или
      DOWNLOAD <filename> <offset>
    """
    parts = request.strip().split()
    if len(parts) not in (2, 3):
        return None

    _, filename, *rest = parts
    offset = 0

    if rest:
        try:
            offset = int(rest[0])
            if offset < 0:
                return None
        except ValueError:
            return None

    return filename, offset


def _send_line(sock, message: str, level: str = "info") -> bool:
    colored = colorize(message, level=level)
    try:
        sock.sendall(f"{colored}\n".encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        log.debug(f"Send skipped: client closed connection before '{message}'")
        return False

    log.debug(f"Sent: {message}")
    return True


def handle_download(client_socket, request: str) -> None:
    parsed = parse_download_command(request)
    if parsed is None:
        _send_line(client_socket, "ERROR: invalid DOWNLOAD syntax", level="error")
        return

    filename, offset = parsed
    path = os.path.join(BASE_DIR, filename)

    if not os.path.exists(path):
        _send_line(client_socket, "ERROR: file not found", level="error")
        return

    try:
        file_size = os.path.getsize(path)
    except OSError as e:
        log.error(f"Cannot stat file '{path}': {e}")
        _send_line(client_socket, "ERROR: cannot read file", level="error")
        return

    if offset > file_size:
        _send_line(client_socket, "ERROR: invalid offset", level="error")
        return

    remaining = file_size - offset
    if remaining <= 0:
        # Клиент уже всё имеет локально
        if not _send_line(client_socket, "OK 0", level="info"):
            return
        _send_line(
            client_socket,
            f"OK DOWNLOADED {file_size} bytes in 0.000 s, 0.00 KB/s",
            level="info",
        )
        return

    # Сообщаем клиенту, сколько байт сейчас будет отправлено
    if not _send_line(client_socket, f"OK {remaining}", level="info"):
        return

    log.debug(
        f"Starting download: file='{filename}', size={file_size}, "
        f"offset={offset}, remaining={remaining}"
    )

    start = time.perf_counter()
    sent = 0

    try:
        with open(path, "rb") as f:
            f.seek(offset)
            while remaining > 0:
                chunk = f.read(min(BUFFER_SIZE, remaining))
                if not chunk:
                    break

                try:
                    client_socket.sendall(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    log.debug("Connection error during download sendall()")
                    break

                size = len(chunk)
                sent += size
                remaining -= size

                if DOWNLOAD_DELAY_PER_CHUNK > 0:
                    time.sleep(DOWNLOAD_DELAY_PER_CHUNK)
    except OSError as e:
        log.error(f"File read error for '{path}': {e}")
        _send_line(client_socket, "ERROR: cannot read file", level="error")
        return

    duration = time.perf_counter() - start
    expected = file_size - offset

    log.debug(
        f"Download finished: file='{filename}', sent={sent}, expected={expected}"
    )

    if sent == expected:
        speed_kbps = (sent / 1024) / duration if duration > 0 else 0.0
        _send_line(
            client_socket,
            f"OK DOWNLOADED {file_size} bytes in {duration:.3f} s, {speed_kbps:.2f} KB/s",
            level="info",
        )
    else:
        log.debug(
            f"Download interrupted at {offset + sent} of {file_size} bytes"
        )
        return