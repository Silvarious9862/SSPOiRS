# src/handlers/upload.py
from __future__ import annotations

import os
import time
from typing import Final

import socket  # ДОБАВЬ ЭТО, если хочешь обрабатывать socket.timeout

from src.utils import logging as log
from src.utils.colors import colorize


BUFFER_SIZE: Final[int] = 4096
BASE_DIR: Final[str] = "server_files"


def is_upload_command(request: str) -> bool:
    return request.upper().startswith("UPLOAD")


def parse_upload_command(request: str) -> tuple[str, int] | None:
    parts = request.strip().split()
    if len(parts) != 3:
        return None

    _, filename, size_str = parts
    try:
        size = int(size_str)
        if size < 0:
            return None
    except ValueError:
        return None
    return filename, size


def _send_line(sock, message: str, level: str = "info") -> bool:
    colored = colorize(message, level=level)
    try:
        sock.sendall(f"{colored}\n".encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        log.debug(f"Send skipped: client closed connection before '{message}'")
        return False

    log.debug(f"Sent: {message}")
    return True


def handle_upload(client_socket, request: str) -> None:
    parsed = parse_upload_command(request)
    if parsed is None:
        _send_line(client_socket, "ERROR: invalid UPLOAD syntax", level="error")
        return

    filename, total_size = parsed

    os.makedirs(BASE_DIR, exist_ok=True)
    path = os.path.join(BASE_DIR, filename)

    offset = 0
    if os.path.exists(path):
        try:
            offset = os.path.getsize(path)
        except OSError:
            offset = 0
        if offset > total_size:
            offset = 0

    remaining = total_size - offset
    mode = "ab" if offset > 0 else "wb"

    if offset == 0:
        if not _send_line(client_socket, "OK READY", level="info"):
            return
    else:
        if not _send_line(client_socket, f"RESUME {offset}", level="info"):
            return

    if remaining <= 0:
        _send_line(
            client_socket,
            "OK UPLOADED 0 bytes in 0.000 s, 0.00 KB/s",
            level="info",
        )
        return

    log.debug(
        f"Starting upload: file='{filename}', total={total_size}, "
        f"offset={offset}, remaining={remaining}"
    )

    start = time.perf_counter()
    received = 0

    old_timeout = client_socket.gettimeout()
    client_socket.settimeout(None)

    try:
        with open(path, mode) as f:
            while remaining > 0:
                try:
                    chunk = client_socket.recv(min(BUFFER_SIZE, remaining))
                except (ConnectionResetError, BrokenPipeError, OSError, TimeoutError):
                    log.debug("Connection error during upload recv()")
                    break

                if not chunk:
                    log.debug("Client closed connection during upload")
                    break

                f.write(chunk)
                received += len(chunk)
                remaining -= len(chunk)
    except OSError as e:
        log.error(f"File write error for '{path}': {e}")
        _send_line(client_socket, "ERROR: cannot write file", level="error")
        return
    finally:
        client_socket.settimeout(old_timeout)

    duration = time.perf_counter() - start
    done = offset + received

    log.debug(
        f"Upload finished: file='{filename}', "
        f"received={received}, total_done={done}, expected={total_size}"
    )

    if received == total_size - offset:
        speed_kbps = (received / 1024) / duration if duration > 0 else 0.0
        _send_line(
            client_socket,
            f"OK UPLOADED {total_size} bytes in {duration:.3f} s, {speed_kbps:.2f} KB/s",
            level="info",
        )
    else:
        _send_line(
            client_socket,
            f"ERROR: upload interrupted at {done} of {total_size} bytes",
            level="error",
        )