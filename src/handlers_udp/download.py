"""src/handlers_udp/download.py"""
from __future__ import annotations

import os
import socket
import time
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize

BASEDIR: Final[str] = "serverfiles"
CHUNK_SIZE: Final[int] = 1200
WINDOW_SIZE: Final[int] = 8
ACK_TIMEOUT: Final[float] = 0.5
MAX_RETRIES: Final[int] = 20
RECV_BUFSIZE: Final[int] = 4096


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

    return os.path.basename(filename), offset


def build_data_packet(seq: int, chunk: bytes) -> bytes:
    header = f"DATA {seq} {len(chunk)}\n".encode("utf-8")
    return header + chunk


def parse_ack_seq(data: bytes) -> int | None:
    try:
        message = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None

    parts = message.split()
    if len(parts) != 2 or parts[0] != "ACK":
        return None

    try:
        return int(parts[1])
    except ValueError:
        return None


def is_ack_done(data: bytes) -> bool:
    try:
        message = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False

    return message == "ACK DONE"


def wait_for_cumulative_ack(
    server_socket: socket.socket,
    client_addr: tuple[str, int],
    min_expected: int,
) -> int | None:
    old_timeout = server_socket.gettimeout()
    server_socket.settimeout(ACK_TIMEOUT)

    try:
        while True:
            try:
                data, addr = server_socket.recvfrom(RECV_BUFSIZE)
            except (socket.timeout, TimeoutError):
                return None
            except OSError as exc:
                log.debug(f"UDP recvfrom failed while waiting ACK: {exc}")
                return None

            if addr != client_addr:
                log.debug(
                    f"Ignored datagram from {addr[0]}:{addr[1]} while waiting "
                    f"ACK from {client_addr[0]}:{client_addr[1]}"
                )
                continue

            ack_seq = parse_ack_seq(data)
            if ack_seq is None:
                log.debug(
                    f"Ignored non-ACK datagram from "
                    f"{addr[0]}:{addr[1]} while waiting cumulative ACK"
                )
                continue

            if ack_seq >= min_expected:
                return ack_seq
    finally:
        server_socket.settimeout(old_timeout)


def wait_for_ack_done(
    server_socket: socket.socket,
    client_addr: tuple[str, int],
) -> bool:
    old_timeout = server_socket.gettimeout()
    server_socket.settimeout(ACK_TIMEOUT)

    try:
        while True:
            try:
                data, addr = server_socket.recvfrom(RECV_BUFSIZE)
            except (socket.timeout, TimeoutError):
                return False
            except OSError as exc:
                log.debug(f"UDP recvfrom failed while waiting ACK DONE: {exc}")
                return False

            if addr != client_addr:
                log.debug(
                    f"Ignored datagram from {addr[0]}:{addr[1]} while waiting "
                    f"ACK DONE from {client_addr[0]}:{client_addr[1]}"
                )
                continue

            if is_ack_done(data):
                return True

            log.debug(
                f"Ignored unexpected datagram from "
                f"{addr[0]}:{addr[1]} while waiting ACK DONE"
            )
    finally:
        server_socket.settimeout(old_timeout)


def handle_download(server_socket, client_addr: tuple[str, int], request: str) -> None:
    parsed = parse_download_command(request)
    if parsed is None:
        send_line(server_socket, client_addr, "ERROR invalid DOWNLOAD syntax", level="error")
        return

    filename, offset = parsed
    path = os.path.join(BASEDIR, filename)

    if not os.path.exists(path):
        send_line(server_socket, client_addr, "ERROR file not found", level="error")
        return

    try:
        filesize = os.path.getsize(path)
    except OSError as exc:
        log.error(f"Cannot stat file {path}: {exc}")
        send_line(server_socket, client_addr, "ERROR cannot read file", level="error")
        return

    if offset > filesize:
        send_line(server_socket, client_addr, "ERROR invalid offset", level="error")
        return

    remaining = filesize - offset
    if not send_line(
        server_socket,
        client_addr,
        f"OK {remaining} {CHUNK_SIZE} {WINDOW_SIZE}",
        level="info",
    ):
        return
    
    if remaining == 0:
        log.info(f"UDP download skipped file={filename}, nothing to send")
        return

    '''if remaining == 0:
        for _ in range(MAX_RETRIES):
            if not send_line(server_socket, client_addr, "DONE", level="info"):
                return
            if wait_for_ack_done(server_socket, client_addr):
                log.info(f"UDP download finished file={filename}, bytes=0")
                return
        return'''

    packets: list[bytes] = []
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                packets.append(build_data_packet(len(packets), chunk))
    except OSError as exc:
        log.error(f"File read error for {path}: {exc}")
        send_line(server_socket, client_addr, "ERROR cannot read file", level="error")
        return

    total_packets = len(packets)
    base = 0
    next_seq = 0
    retries = 0
    start = time.perf_counter()

    log.debug(
        f"Starting UDP download file={filename}, size={filesize}, offset={offset}, "
        f"remaining={remaining}, packets={total_packets}, "
        f"chunk_size={CHUNK_SIZE}, window={WINDOW_SIZE}"
    )

    while base < total_packets:
        while next_seq < total_packets and next_seq < base + WINDOW_SIZE:
            try:
                server_socket.sendto(packets[next_seq], client_addr)
            except OSError as exc:
                log.debug(f"UDP send DATA failed: {exc}")
                return
            next_seq += 1

        ack_seq = wait_for_cumulative_ack(server_socket, client_addr, base)

        if ack_seq is None:
            retries += 1
            if retries > MAX_RETRIES:
                log.debug(
                    f"UDP download interrupted: ACK timeout window base={base}, "
                    f"client={client_addr[0]}:{client_addr[1]}"
                )
                return

            log.debug(
                f"ACK timeout: retransmit window base={base}, next_seq={next_seq}, "
                f"retry={retries}/{MAX_RETRIES}"
            )

            for seq in range(base, next_seq):
                try:
                    server_socket.sendto(packets[seq], client_addr)
                except OSError as exc:
                    log.debug(f"UDP resend DATA failed: {exc}")
                    return
            continue

        if ack_seq >= total_packets:
            ack_seq = total_packets - 1

        if ack_seq < base:
            continue

        base = ack_seq + 1
        retries = 0

    duration = time.perf_counter() - start
    speed_kbps = remaining / 1024 / duration if duration > 0 else 0.0

    for _ in range(MAX_RETRIES):
        if not send_line(server_socket, client_addr, "DONE", level="info"):
            return
        if wait_for_ack_done(server_socket, client_addr):
            log.info(
                f"UDP download finished file={filename}, bytes={remaining}, "
                f"time={duration:.3f}s, speed={speed_kbps:.2f} KB/s"
            )
            summary = (
                f"OK DOWNLOADED {remaining} bytes in {duration:.3f} s, "
                f"{speed_kbps:.2f} KB/s"
            )
            send_line(server_socket, client_addr, summary, level="info")
            return

    log.debug(
        f"UDP download finished without final ACK DONE from "
        f"{client_addr[0]}:{client_addr[1]}"
    )

    