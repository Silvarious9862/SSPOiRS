from __future__ import annotations

from datetime import datetime

from src.models.tcp_session import TcpSession
from src.utils.colors import colorize


def is_time_command(request: str) -> bool:
    return request.strip().upper() == "TIME"


def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def handle_time(session: TcpSession, request: str) -> None:
    if not is_time_command(request):
        session.out_buffer.extend(b"ERROR unknown command\n")
        return

    time = colorize(get_current_time(), level="info")
    session.out_buffer.extend(f"{time}\n".encode("utf-8"))