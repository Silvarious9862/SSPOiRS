"""src/handlers_udp/upload.py"""
from __future__ import annotations

import os
import socket
import time
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize

BASEDIR: Final[str] = "serverfiles"
CHUNK_SIZE: Final[int] = 1450
RECV_BUFSIZE: Final[int] = 65535
ACK_TIMEOUT: Final[float] = 0.1
MAX_RETRIES: Final[int] = 20


def send_line(
    server_socket,
    client_addr: tuple[str, int],
    message: str,
    level: str = "info",
) -> bool:
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


def parse_data_packet(data: bytes) -> tuple[int, bytes] | None:
    header, sep, payload = data.partition(b"\n")
    if not sep:
        return None

    try:
        header_text = header.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None

    parts = header_text.split()
    if len(parts) != 3 or parts[0] != "DATA":
        return None

    try:
        seq = int(parts[1])
        size = int(parts[2])
    except ValueError:
        return None

    if size < 0 or len(payload) != size:
        return None

    return seq, payload


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
            if not send_line(server_socket, client_addr, f"RESUME {offset}", level="info"):
                return
        elif offset == total_size:
            # Уже всё загружено
            if not send_line(server_socket, client_addr, f"RESUME {offset}", level="info"):
                return
            summary = f"OK UPLOADED 0 bytes in 0.000 s, 0.00 KB/s"
            send_line(server_socket, client_addr, summary, level="info")
            return
        else:
            if not send_line(server_socket, client_addr, "OK READY", level="info"):
                return
    else:
        if not send_line(server_socket, client_addr, "OK READY", level="info"):
            return

    remaining = total_size - offset
    if remaining == 0:
        summary = f"OK UPLOADED 0 bytes in 0.000 s, 0.00 KB/s"
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

        expected_seq = offset // CHUNK_SIZE  # номер ожидаемого блока
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

            # DONE от клиента
            try:
                text = data.decode("utf-8").strip()
            except UnicodeDecodeError:
                text = None

            if text == "DONE":
                try:
                    server_socket.sendto(b"ACK DONE", client_addr)
                except OSError as exc:
                    log.debug(f"UDP send ACK DONE failed: {exc}")
                break

            # иначе ожидаем DATA-пакет
            parsed = parse_data_packet(data)
            if parsed is None:
                log.debug(
                    f"Ignored non-DATA datagram from "
                    f"{addr[0]}:{addr[1]} while waiting DATA"
                )
                continue

            seq, payload = parsed

            if seq == expected_seq:
                try:
                    f.write(payload)
                except OSError as exc:
                    log.error(f"File write error for {path}: {exc}")
                    send_line(
                        server_socket,
                        client_addr,
                        "ERROR cannot write file",
                        level="error",
                    )
                    return

                received += len(payload)
                expected_seq += 1

                ack_seq = expected_seq - 1
                try:
                    server_socket.sendto(f"ACK {ack_seq}".encode("utf-8"), client_addr)
                except OSError as exc:
                    log.debug(f"UDP send ACK failed: {exc}")
                    return
            else:
                # повторяем ACK последней подтверждённой последовательности
                ack_seq = expected_seq - 1
                try:
                    server_socket.sendto(f"ACK {ack_seq}".encode("utf-8"), client_addr)
                except OSError as exc:
                    log.debug(f"UDP resend ACK failed: {exc}")
                    return

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