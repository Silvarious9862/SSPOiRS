# src/handlers_poll/download.py
from __future__ import annotations

from typing import Final

from src.models.tcp_session import TcpSession

BUFFERSIZE: Final[int] = 4096
BASEDIR: Final[str] = "serverfiles"
OOB_PROGRESS_STEP: Final[int] = 10


def is_download_command(request: str) -> bool:
    return request.upper().startswith("DOWNLOAD")


def parse_download_command(request: str) -> tuple[str, int] | None:
    raise NotImplementedError


def sanitize_download_filename(filename: str) -> str:
    raise NotImplementedError


def prepare_download(session: TcpSession, filename: str, offset: int) -> None:
    raise NotImplementedError


def handle_download_start(session: TcpSession, request: str) -> None:
    raise NotImplementedError


def continue_download_send(session: TcpSession) -> None:
    raise NotImplementedError


def finalize_download(session: TcpSession) -> None:
    raise NotImplementedError


def abort_download(session: TcpSession, reason: str) -> None:
    raise NotImplementedError