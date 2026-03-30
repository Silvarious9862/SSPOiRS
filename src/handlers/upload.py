"""src/handlers/upload.py"""
from __future__ import annotations

import os
import socket
import time
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize

BUFFERSIZE: Final[int] = 4096
BASEDIR: Final[str] = "serverfiles"


def is_upload_command(request: str) -> bool:
    return request.upper().startswith("UPLOAD")


def parse_upload_command(request: str) -> tuple[str, int] | None:
    parts = request.strip().split()
    if len(parts) != 3:
        return None
    _, filename, sizestr = parts
    try:
        size = int(sizestr)
        if size < 0:
            return None
    except ValueError:
        return None
    return filename, size


def send_line(sock, message: str, level: str = "info") -> bool:
    colored = colorize(message, level=level)
    try:
        sock.sendall(f"{colored}\n".encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        log.debug(f"Send skipped — client closed before: {message!r}")
        return False
    log.debug(f"Sent: {message!r}")
    return True


def handle_upload(client_socket, request: str) -> None:
    parsed = parse_upload_command(request)
    if parsed is None:
        send_line(client_socket, "ERROR invalid UPLOAD syntax", level="error")
        return

    filename, total_size = parsed
    os.makedirs(BASEDIR, exist_ok=True)
    path = os.path.join(BASEDIR, filename)

    offset = 0
    if os.path.exists(path):
        try:
            offset = os.path.getsize(path)
        except OSError:
            offset = 0
    if offset >= total_size:
        offset = 0

    remaining = total_size - offset
    mode = "ab" if offset > 0 else "wb"

    if offset > 0:
        if not send_line(client_socket, f"RESUME {offset}", level="info"):
            return
    else:
        if not send_line(client_socket, "OK READY", level="info"):
            return

    if remaining == 0:
        send_line(client_socket,
                  "OK UPLOADED 0 bytes in 0.000 s, 0.00 KB/s",
                  level="info")
        return

    log.debug(f"Starting upload file={filename}, total={total_size}, "
              f"offset={offset}, remaining={remaining}")
    start = time.perf_counter()
    received = 0
    old_timeout = client_socket.gettimeout()
    client_socket.settimeout(None)

    try:
        with open(path, mode) as f:
            while remaining > 0:
                try:
                    chunk = client_socket.recv(min(BUFFERSIZE, remaining))
                except (ConnectionResetError, BrokenPipeError,
                        OSError, TimeoutError) as exc:
                    log.debug(f"Connection error during upload recv: {exc}")
                    break
                if not chunk:
                    log.debug("Client closed connection during upload")
                    break
                f.write(chunk)
                received += len(chunk)
                remaining -= len(chunk)
    except OSError as e:
        log.error(f"File write error for {path}: {e}")
        send_line(client_socket, "ERROR cannot write file", level="error")
        return
    finally:
        client_socket.settimeout(old_timeout)

    duration = time.perf_counter() - start
    done = offset + received

    if received == total_size - offset:
        speed_kbps = received / 1024 / duration if duration > 0 else 0.0
        send_line(client_socket,
                  f"OK UPLOADED {total_size} bytes in {duration:.3f} s, "
                  f"{speed_kbps:.2f} KB/s",
                  level="info")
    else:
        send_line(client_socket,
                  f"ERROR upload interrupted at {done} of {total_size} bytes",
                  level="error")