from __future__ import annotations

from src.models.tcp_session import TcpSession
from src.utils.colors import colorize
from src.utils import logging as log


def is_echo_command(request: str) -> bool:
    return request.upper().startswith("ECHO")


def extract_echo_message(request: str) -> str:
    return request[4:].strip()


def handle_echo(session: TcpSession, request: str) -> None:
    if not is_echo_command(request):
        session.out_buffer.extend(b"ERROR unknown command\n")
        return

    message = extract_echo_message(request)
    if not message:
        session.out_buffer.extend(b"ERROR empty echo message\n")
        return
    message_colored = colorize(message, level = "info")
    session.out_buffer.extend(f"{message_colored}\n".encode("utf-8"))

    host, port = session.addr
    log.debug(f"Sent to {host}:{port}: {message!r}")