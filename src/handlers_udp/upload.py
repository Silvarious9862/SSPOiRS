"""src/handlers_udp/upload.py"""
from __future__ import annotations

import os
import socket
import time
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize

BASEDIR: Final[str] = "serverfiles"
RECV_BUFSIZE: Final[int] = 65535
ACK_TIMEOUT: Final[float] = 0.5
MAX_RETRIES: Final[int] = 20


def send_line(server_socket, client_addr: tuple[str, int], message: str, level: str = "info") -> bool:
    colored = colorize(message, level=level)
    try:
        server_socket.sendto(f"{colored}\n".encode("utf-8"), client_addr)
    except OSError as exc:
        log.debug(
            f"UDP send skipped to {client_addr[0]}:{client_addr[1]} "
            f"before {message!r}: {exc}"
        )
        return False

    log.debug(f"Sent to {client_addr[0]}:{client_addr[1]}: {message!r}")
    return True


def parse_upload_command(request: str) -> tuple[str, int] | None:
    parts = request.strip().split()
    if len(parts) != 3:
        return None

    _, filename, size_str = parts
    try:
        total_size = int(size_str)
        if total_size <= 0:
            return None
    except ValueError:
        return None

    return os.path.basename(filename), total_size


def wait_for_ready_or_resume(
    server_socket: socket.socket,
    client_addr: tuple[str, int],
) -> int | None:
    """
    Ждём от клиента 'OK READY' или 'RESUME <offset>'.
    Возвращаем offset (0 или >0) или None при ошибке/таймауте.
    """
    old_timeout = server_socket.gettimeout()
    server_socket.settimeout(ACK_TIMEOUT)

    try:
        while True:
            try:
                data, addr = server_socket.recvfrom(RECV_BUFSIZE)
            except (socket.timeout, TimeoutError):
                return None
            except OSError as exc:
                log.debug(f"UDP recvfrom failed while waiting READY/RESUME: {exc}")
                return None

            if addr != client_addr:
                log.debug(
                    f"Ignored datagram from {addr[0]}:{addr[1]} while waiting "
                    f"READY/RESUME from {client_addr[0]}:{client_addr[1]}"
                )
                continue

            try:
                message = data.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue

            if message == "OK READY":
                return 0

            if message.startswith("RESUME "):
                parts = message.split()
                if len(parts) != 2:
                    return None
                try:
                    offset = int(parts[1])
                    if offset < 0:
                        return None
                    return offset
                except ValueError:
                    return None

            log.debug(
                f"Ignored unexpected datagram {message!r} from "
                f"{addr[0]}:{addr[1]} while waiting READY/RESUME"
            )
    finally:
        server_socket.settimeout(old_timeout)


def handle_upload(server_socket, client_addr: tuple[str, int], request: str) -> None:
    parsed = parse_upload_command(request)
    if parsed is None:
        send_line(server_socket, client_addr, "ERROR invalid UPLOAD syntax", level="error")
        return

    filename, total_size = parsed
    os.makedirs(BASEDIR, exist_ok=True)
    path = os.path.join(BASEDIR, filename)

    offset = 0
    if os.path.exists(path):
        try:
            offset = os.path.getsize(path)
        except OSError as exc:
            log.error(f"Cannot stat file {path}: {exc}")
            send_line(server_socket, client_addr, "ERROR cannot stat file", level="error")
            return

        if offset > total_size:
            send_line(server_socket, client_addr, "ERROR invalid local file size", level="error")
            return

        if 0 < offset < total_size:
            # Предлагаем докачку
            if not send_line(server_socket, client_addr, f"RESUME {offset}", level="info"):
                return
        elif offset == total_size:
            # Уже всё загружено
            summary = f"OK UPLOADED {total_size} bytes in 0.000 s, 0.00 KB/s"
            send_line(server_socket, client_addr, summary, level="info")
            return
        else:
            # offset == 0 или файл пустой
            if not send_line(server_socket, client_addr, "OK READY", level="info"):
                return
    else:
        if not send_line(server_socket, client_addr, "OK READY", level="info"):
            return

    # Ждём подтверждение от клиента (OK READY / RESUME <offset>)
    confirmed_offset = wait_for_ready_or_resume(server_socket, client_addr)
    if confirmed_offset is None:
        log.debug(
            f"UDP upload aborted: no READY/RESUME from "
            f"{client_addr[0]}:{client_addr[1]}"
        )
        return

    if confirmed_offset != offset:
        log.debug(
            f"UDP upload offset mismatch: server={offset}, client={confirmed_offset}"
        )
        offset = confirmed_offset

    remaining = total_size - offset
    if remaining == 0:
        summary = f"OK UPLOADED {total_size} bytes in 0.000 s, 0.00 KB/s"
        send_line(server_socket, client_addr, summary, level="info")
        return

    mode = "r+b" if os.path.exists(path) else "wb"
    try:
        f = open(path, mode)
    except OSError as exc:
        log.error(f"Cannot open file {path} for writing: {exc}")
        send_line(server_socket, client_addr, "ERROR cannot open file", level="error")
        return

    with f:
        if offset > 0:
            f.seek(offset)

        log.debug(
            f"Starting UDP upload file={filename}, total={total_size}, "
            f"offset={offset}, remaining={remaining}"
        )

        received = 0
        start = time.perf_counter()

        while received < remaining:
            try:
                data, addr = server_socket.recvfrom(RECV_BUFSIZE)
            except (socket.timeout, TimeoutError):
                log.debug(
                    f"UDP upload timeout waiting DATA from "
                    f"{client_addr[0]}:{client_addr[1]}"
                )
                return
            except OSError as exc:
                log.debug(f"UDP recv DATA failed: {exc}")
                return

            if addr != client_addr:
                log.debug(
                    f"Ignored DATA datagram from {addr[0]}:{addr[1]} "
                    f"while uploading from {client_addr[0]}:{client_addr[1]}"
                )
                continue

            try:
                text = data.decode("utf-8").strip()
            except UnicodeDecodeError:
                text = None

            if text == "DONE":
                # Клиент закончил, подтверждаем
                try:
                    server_socket.sendto(b"ACK DONE", client_addr)
                except OSError as exc:
                    log.debug(f"UDP send ACK DONE failed: {exc}")
                break

            # Иначе считаем, что это «сырые» данные файла
            try:
                f.write(data)
            except OSError as exc:
                log.error(f"File write error for {path}: {exc}")
                send_line(server_socket, client_addr, "ERROR cannot write file", level="error")
                return

            received += len(data)

        duration = time.perf_counter() - start
        speed_kbps = received / 1024 / duration if duration > 0 else 0.0

        log.info(
            f"UDP upload finished file={filename}, bytes={received}, "
            f"time={duration:.3f}s, speed={speed_kbps:.2f} KB/s"
        )

        summary = (
            f"OK UPLOADED {offset + received} bytes in {duration:.3f} s, "
            f"{speed_kbps:.2f} KB/s"
        )
        send_line(server_socket, client_addr, summary, level="info")