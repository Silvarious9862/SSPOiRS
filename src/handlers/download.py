"""src/handlers/download.py"""
from __future__ import annotations

import os
import time
import socket
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize

BUFFERSIZE: Final[int] = 4096
BASEDIR: Final[str] = "serverfiles"
DOWNLOAD_DELAY_PER_CHUNK: float = 0.00
OOB_PROGRESS_STEP: Final[int] = 10


def is_download_command(request: str) -> bool:
    return request.upper().startswith("DOWNLOAD")


def parse_download_command(request: str) -> tuple[str, int] | None:
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


def send_line(sock, message: str, level: str = "info") -> bool:
    colored = colorize(message, level=level)
    try:
        sock.sendall(f"{colored}\n".encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        log.debug(f"Send skipped — client closed before: {message!r}")
        return False
    log.debug(f"Sent: {message!r}")
    return True

def send_oob_progress(sock, percent: int) -> None:
    """
    Отправить процент прогресса как 1 байт TCP urgent data.
    Значение должно быть в диапазоне 0..100.
    """
    try:
        sock.send(bytes([percent]), socket.MSG_OOB)
    except (BrokenPipeError, ConnectionResetError, OSError, ValueError) as exc:
        log.debug(f"OOB send skipped: {exc}")

def handle_download(client_socket, request: str) -> None:
    parsed = parse_download_command(request)
    if parsed is None:
        send_line(client_socket, "ERROR invalid DOWNLOAD syntax", level="error")
        return

    filename, offset = parsed
    path = os.path.join(BASEDIR, filename)

    if not os.path.exists(path):
        send_line(client_socket, "ERROR file not found", level="error")
        return

    try:
        filesize = os.path.getsize(path)
    except OSError as e:
        log.error(f"Cannot stat file {path}: {e}")
        send_line(client_socket, "ERROR cannot read file", level="error")
        return

    if offset > filesize:
        send_line(client_socket, "ERROR invalid offset", level="error")
        return

    remaining = filesize - offset

    if remaining == 0:
        if not send_line(client_socket, "OK 0", level="info"):
            return
        send_line(client_socket,
                  f"OK DOWNLOADED {filesize} bytes in 0.000 s, 0.00 KB/s",
                  level="info")
        return

    if not send_line(client_socket, f"OK {remaining}", level="info"):
        return

    log.debug(f"Starting download file={filename}, size={filesize}, "
              f"offset={offset}, remaining={remaining}")
    start = time.perf_counter()
    sent = 0
    last_oob_step = -1
    expected = filesize - offset

    try:
        with open(path, "rb") as f:
            f.seek(offset)
            while remaining > 0:
                chunk = f.read(min(BUFFERSIZE, remaining))
                if not chunk:
                    break
                try:
                    client_socket.sendall(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    # Разрыв во время передачи — keepalive его уже зафиксировал;
                    # сервер прекращает попытку без финального OK.
                    log.debug(f"Connection error during download sendall: {exc}")
                    break
                size = len(chunk)
                sent += size
                remaining -= size

                # Обычные данные: считаем и выводим отдельно, без OOB
                if expected > 0:
                    percent = int(sent * 100 / expected)
                    step = percent // OOB_PROGRESS_STEP
                    if step > last_oob_step:
                        log.debug(
                            f"DOWNLOAD sent regular bytes: {sent}/{expected} "
                            f"({min(step * OOB_PROGRESS_STEP, 100)}%)"
                        )

                # Внеполосные данные: отправляем процент шагами
                if expected > 0:
                    percent = int(sent * 100 / expected)
                    step = percent // OOB_PROGRESS_STEP

                    if step > last_oob_step and percent < 100:
                        oob_percent = min(step * OOB_PROGRESS_STEP, 99)
                        send_oob_progress(client_socket, oob_percent)
                        last_oob_step = step

                if DOWNLOAD_DELAY_PER_CHUNK > 0:
                    time.sleep(DOWNLOAD_DELAY_PER_CHUNK)
    except OSError as e:
        log.error(f"File read error for {path}: {e}")
        send_line(client_socket, "ERROR cannot read file", level="error")
        return

    duration = time.perf_counter() - start
    expected = filesize - offset

    if sent == expected:
        send_oob_progress(client_socket, 100)
        log.info(f"DOWNLOAD finished, regular bytes sent: {sent}")

        speed_kbps = sent / 1024 / duration if duration > 0 else 0.0
        send_line(client_socket,
                f"OK DOWNLOADED {filesize} bytes in {duration:.3f} s, "
                f"{speed_kbps:.2f} KB/s",
                level="info")
    else:
        log.debug(f"Download interrupted at offset {offset + sent} of {filesize} bytes")