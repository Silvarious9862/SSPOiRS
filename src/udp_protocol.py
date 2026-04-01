"""src/udp_protocol.py — UDP protocol layer."""
from __future__ import annotations

import socket
from typing import Final

from src.handlers.close import is_close_command
from src.handlers.echo import handle_echo, is_echo_command
from src.handlers.time_ import handle_time, is_time_command
from src.handlers.upload import is_upload_command
from src.handlers.download import is_download_command
from src.handlers_udp.upload import handle_upload
from src.handlers_udp.download import handle_download
from src.utils import logging as log
from src.utils.colors import colorize

BUFFERSIZE: Final[int] = 4096
SOCKET_TIMEOUT: Final[float] = 0.5


def create_server_socket(host: str, port: int) -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.settimeout(SOCKET_TIMEOUT)
    return server_socket


def receive_request(
    server_socket: socket.socket,
) -> tuple[str, tuple[str, int]] | None:
    try:
        data, client_addr = server_socket.recvfrom(BUFFERSIZE)
    except (socket.timeout, TimeoutError):
        return None
    except OSError as exc:
        log.debug(f"UDP recvfrom failed: {exc}")
        return None

    try:
        request = data.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        log.debug(
            f"Ignored non-UTF8 datagram from "
            f"{client_addr[0]}:{client_addr[1]}"
        )
        return None
    
    if not request:
        log.debug(f"Ignored empty datagram from {client_addr[0]}:{client_addr[1]}")
        return None
    
    log.debug(f"Received from {client_addr[0]}:{client_addr[1]}: {request!r}")
    return request, client_addr


def send_response(
    server_socket: socket.socket,
    client_addr: tuple[str, int],
    message: str,
    *,
    level: str = "info",
) -> bool:
    colored_message = colorize(message, level=level)
    try:
        server_socket.sendto(f"{colored_message}\n".encode("utf-8"), client_addr)
    except OSError as exc:
        log.debug(
            f"Send skipped to {client_addr[0]}:{client_addr[1]} "
            f"before {message!r}: {exc}"
        )
        return False

    log.debug(f"Sent to {client_addr[0]}:{client_addr[1]}: {message!r}")
    return True


def send_hello(
    server_socket: socket.socket,
    client_addr: tuple[str, int],
) -> bool:
    return send_response(server_socket, client_addr, "HELLO", level="info")


def build_response(request: str) -> tuple[str, str, bool]:
    if not request:
        return "ERROR empty request", "error", False

    request = request.strip()

    if is_close_command(request):
        return "BYE", "info", True
    if is_echo_command(request):
        return handle_echo(request), "info", False
    if is_time_command(request):
        return handle_time(request), "info", False

    return "ERROR unknown command", "error", False


def handle_datagram(
    server_socket: socket.socket,
    request: str,
    client_addr: tuple[str, int],
) -> None:
    req_stripped = request.strip()

    if is_upload_command(req_stripped):
        handle_upload(server_socket, client_addr, req_stripped)
        return

    if is_download_command(req_stripped):
        handle_download(server_socket, client_addr, req_stripped)
        return

    response, level, should_close = build_response(req_stripped)
    if not send_response(server_socket, client_addr, response, level=level):
        return

    if should_close:
        log.info(f"UDP client finished {client_addr[0]}:{client_addr[1]}")