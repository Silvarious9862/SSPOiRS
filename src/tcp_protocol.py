# src/tcp_protocol.py
from __future__ import annotations

import socket
from typing import Final

from src.handlers.close import is_close_command
from src.handlers.echo import handle_echo, is_echo_command
from src.handlers.time_ import handle_time, is_time_command
from src.handlers.upload import is_upload_command, handle_upload
from src.handlers.download import is_download_command, handle_download
from src.utils import logging as log
from src.utils.colors import colorize

BUFFER_SIZE: Final[int] = 4096
BACKLOG: Final[int] = 5
SOCKET_TIMEOUT: Final[float] = 0.5


def create_listen_socket(host: str, port: int) -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(BACKLOG)
    server_socket.settimeout(SOCKET_TIMEOUT)
    return server_socket


def accept_client(
    server_socket: socket.socket,
) -> tuple[socket.socket, tuple[str, int]] | None:
    try:
        client_socket, client_addr = server_socket.accept()
    except socket.timeout:
        return None

    client_socket.settimeout(SOCKET_TIMEOUT)
    log.info(f"Client connected: {client_addr[0]}:{client_addr[1]}")
    return client_socket, client_addr


def receive_request(client_socket: socket.socket) -> str | None:
    try:
        data = client_socket.recv(BUFFER_SIZE)
    except (socket.timeout, TimeoutError):
        return None
    except (ConnectionResetError, BrokenPipeError, OSError):
        return ""

    if not data:
        return ""

    request = data.decode("utf-8").strip()
    log.debug(f"Received: {request}")
    return request


def send_response(client_socket: socket.socket, message: str, level: str = "info") -> bool:
    colored_message = colorize(message, level=level)

    try:
        client_socket.sendall(f"{colored_message}\n".encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        log.debug(f"Send skipped: client closed connection before '{message}'")
        return False

    log.debug(f"Sent: {message}")
    return True


def send_hello(client_socket: socket.socket) -> bool:
    return send_response(client_socket, "HELLO", level="info")


def build_response(request: str) -> tuple[str, str, bool]:
    """
    Возвращает (message, level, should_close) только для простых команд.
    UPLOAD/DOWNLOAD здесь не обрабатываются — ими занимаются отдельные хендлеры.
    """
    if not request:
        return "ERROR: empty request", "error", False

    request = request.strip()

    if is_close_command(request):
        return "BYE", "info", True

    if is_echo_command(request):
        return handle_echo(request), "info", False

    if is_time_command(request):
        return handle_time(request), "info", False

    return "ERROR: unknown command", "error", False


def close_client(client_socket: socket.socket, client_addr: tuple[str, int]) -> None:
    try:
        client_socket.close()
    finally:
        log.info(f"Client disconnected: {client_addr[0]}:{client_addr[1]}")


def handle_client(client_socket: socket.socket, client_addr: tuple[str, int]) -> None:
    try:
        if not send_hello(client_socket):
            return

        while True:
            request = receive_request(client_socket)

            if request is None:
                # timeout — просто ждём дальше
                continue

            if request == "":
                # клиент закрыл соединение
                break

            req_stripped = request.strip()

            # Файловые команды
            if is_upload_command(req_stripped):
                handle_upload(client_socket, req_stripped)
                # после завершения upload остаёмся в цикле команд
                continue

            if is_download_command(req_stripped):
                handle_download(client_socket, req_stripped)
                continue

            # Обычные текстовые команды
            response, level, should_close = build_response(req_stripped)
            if not send_response(client_socket, response, level=level):
                break

            if should_close:
                break

    except KeyboardInterrupt:
        send_response(client_socket, "SERVER SHUTDOWN", level="warn")
        raise
    finally:
        close_client(client_socket, client_addr)