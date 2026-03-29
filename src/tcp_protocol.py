# src/tcp_protocol.py
from __future__ import annotations

import socket
from typing import Final

from src.handlers.close import is_close_command
from src.handlers.echo import handle_echo
from src.utils import logging as log
from src.utils.colors import colorize

BUFFER_SIZE: Final[int] = 4096
BACKLOG: Final[int] = 5


def create_listen_socket(host: str, port: int) -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(BACKLOG)
    return server_socket


def accept_client(server_socket: socket.socket) -> tuple[socket.socket, tuple[str, int]]:
    client_socket, client_addr = server_socket.accept()
    log.info(f"Client connected: {client_addr[0]}:{client_addr[1]}")
    return client_socket, client_addr


def receive_request(client_socket: socket.socket) -> str:
    data = client_socket.recv(BUFFER_SIZE)
    request = data.decode("utf-8").strip()
    log.debug(f"Received: {request}")
    return request


def send_response(client_socket: socket.socket, message: str, level: str = "info") -> None:
    colored_message = colorize(message, level=level)
    client_socket.sendall(f"{colored_message}\n".encode("utf-8"))
    log.debug(f"Sent: {message}")


def send_hello(client_socket: socket.socket) -> None:
    send_response(client_socket, "HELLO", level="info")


def build_response(request: str) -> tuple[str, str, bool]:
    if not request:
        return "ERROR: empty request", "error", False

    if is_close_command(request):
        return "BYE", "info", True

    if request.upper().startswith("ECHO"):
        return handle_echo(request), "info", False

    return "ERROR: unknown command", "error", False


def close_client(client_socket: socket.socket, client_addr: tuple[str, int]) -> None:
    client_socket.close()
    log.info(f"Client disconnected: {client_addr[0]}:{client_addr[1]}")


def handle_client(client_socket: socket.socket, client_addr: tuple[str, int]) -> None:
    try:
        send_hello(client_socket)

        while True:
            request = receive_request(client_socket)
            if not request:
                break

            response, level, should_close = build_response(request)
            send_response(client_socket, response, level=level)

            if should_close:
                break
    finally:
        close_client(client_socket, client_addr)
