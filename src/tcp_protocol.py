"""src/tcp_protocol.py — TCP protocol layer with SO_KEEPALIVE support."""
from __future__ import annotations

import socket
import threading
import struct
from typing import Final

from src.handlers.close import is_close_command
from src.handlers.echo import handle_echo, is_echo_command
from src.handlers.time_ import handle_time, is_time_command
from src.handlers.upload import is_upload_command, handle_upload
from src.handlers.download import is_download_command, handle_download
from src.utils import logging as log
from src.utils.colors import colorize
from src.utils.runtime import shutdown_event, clients_lock, active_clients

BUFFERSIZE: Final[int] = 4096
BACKLOG: Final[int] = 5
SOCKET_TIMEOUT: Final[float] = 0.5

KEEPALIVE_IDLE: Final[int] = 15   # секунд простоя до первой пробы
KEEPALIVE_INTVL: Final[int] = 5   # интервал между повторными пробами
KEEPALIVE_CNT: Final[int] = 4     # число проб до признания разрыва


def _apply_keepalive(sock: socket.socket) -> None:
    """Включить SO_KEEPALIVE на сокете (кроссплатформенно)."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    if hasattr(socket, "TCP_KEEPIDLE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, KEEPALIVE_IDLE)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, KEEPALIVE_INTVL)
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, KEEPALIVE_CNT)

    if hasattr(socket, "SIO_KEEPALIVE_VALS"):
        sock.ioctl(
            socket.SIO_KEEPALIVE_VALS,
            (1, KEEPALIVE_IDLE * 1000, KEEPALIVE_INTVL * 1000),
        )

    log.debug(
        f"SO_KEEPALIVE enabled: idle={KEEPALIVE_IDLE}s "
        f"intvl={KEEPALIVE_INTVL}s cnt={KEEPALIVE_CNT}"
    )

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
    _apply_keepalive(client_socket)          # ← keepalive на каждом клиенте
    log.info(f"Client connected {client_addr[0]}:{client_addr[1]}")
    return client_socket, client_addr


def set_client_state(client_addr, state: str) -> None:
    with clients_lock:
        info = active_clients.get(client_addr)
        if info is not None:
            info["state"] = state


def receive_request(
    client_socket: socket.socket,
    client_addr: tuple[str, int],
) -> str | None:
    worker_name = threading.current_thread().name
    host, port = client_addr

    try:
        data = client_socket.recv(BUFFERSIZE)
    except (socket.timeout, TimeoutError):
        return None
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        if shutdown_event.is_set():
            log.debug(
                f"{worker_name} | Receive interrupted by shutdown"
            )
        else:
            log.debug(
                f"{worker_name} | Receive failed: {exc}"
            )
        return ""

    if not data:
        log.debug(f"{worker_name} | Client closed connection")
        return ""

    request = data.decode("utf-8").strip()
    log.debug(f"{worker_name} | Received: {request!r}")
    return request


def send_response(
    client_socket: socket.socket,
    message: str,
    *,
    level: str = "info",
    client_addr: tuple[str, int] | None = None,
) -> bool:
    colored_message = colorize(message, level=level)
    worker_name = threading.current_thread().name

    if client_addr is None:
        try:
            client_addr = client_socket.getpeername()
        except OSError:
            client_addr = ("unknown", 0)

    host, port = client_addr[0], client_addr[1]

    try:
        client_socket.sendall(f"{colored_message}\n".encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        log.debug(
            f"{worker_name} | Send skipped "
            f"(client closed before): {message!r}"
        )
        return False

    log.debug(f"{worker_name} | Sent: {message!r}")
    return True


def send_hello(client_socket: socket.socket, client_addr: tuple[str, int]) -> bool:
    return send_response(client_socket, "HELLO", level="info", client_addr=client_addr)


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


def close_client(
    client_socket: socket.socket, client_addr: tuple[str, int]
) -> None:
    try:
        client_socket.close()
    finally:
        log.info(f"Client disconnected {client_addr[0]}:{client_addr[1]}")


def handle_client(
    client_socket: socket.socket, client_addr: tuple[str, int]
) -> None:
    try:
        if not send_hello(client_socket, client_addr):
            set_client_state(client_addr, "idle")
            return
        while True:
            request = receive_request(client_socket, client_addr)
            if request is None:
                continue
            if request == "":
                break
            req_stripped = request.strip()
            if is_upload_command(req_stripped):
                set_client_state(client_addr, "upload")
                handle_upload(client_socket, req_stripped)
                set_client_state(client_addr, "idle")
                continue
            if is_download_command(req_stripped):
                set_client_state(client_addr, "download")
                handle_download(client_socket, req_stripped)
                set_client_state(client_addr, "idle")
                continue
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