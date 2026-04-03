from __future__ import annotations

from src.models.tcp_session import TcpSession, mark_session_closing
from src.utils.colors import colorize
from src.utils import logging as log

CLOSE_COMMANDS = {"CLOSE", "EXIT", "QUIT"}


def is_close_command(request: str) -> bool:
    return request.strip().upper() in CLOSE_COMMANDS


def handle_close(session: TcpSession, request: str) -> None:
    if not is_close_command(request):
        session.out_buffer.extend(b"ERROR unknown command\n")
        return

    bye = colorize("BYE", level="info")
    session.out_buffer.extend(f"{bye}\n".encode("utf-8"))

    host, port = session.addr
    log.debug(f"Sent to {host}:{port}: BYE")
    
    mark_session_closing(session)