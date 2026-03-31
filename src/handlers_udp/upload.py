"""src/handlers_udp/upload.py"""
from __future__ import annotations

from src.utils import logging as log
from src.utils.colors import colorize


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


def handle_upload(server_socket, client_addr: tuple[str, int], request: str) -> None:
    log.debug(
        f"UDP upload handler placeholder for "
        f"{client_addr[0]}:{client_addr[1]}: {request!r}"
    )
    send_line(
        server_socket,
        client_addr,
        "ERROR UDP UPLOAD not implemented yet",
        level="error",
    )