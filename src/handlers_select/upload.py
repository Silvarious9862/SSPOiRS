# src/handlers_poll/upload.py
from __future__ import annotations

from typing import Final

from src.models.tcp_session import TcpSession

BUFFERSIZE: Final[int] = 4096
BASEDIR: Final[str] = "serverfiles"
OOB_PROGRESS_STEP: Final[int] = 10


def is_upload_command(request: str) -> bool:
    return request.upper().startswith("UPLOAD")


def parse_upload_command(request: str) -> tuple[str, int] | None:
    raise NotImplementedError


def sanitize_upload_filename(filename: str) -> str:
    raise NotImplementedError


def prepare_upload(session: TcpSession, filename: str, total_size: int) -> None:
    raise NotImplementedError


def handle_upload_start(session: TcpSession, request: str) -> None:
    raise NotImplementedError


def continue_upload_receive(session: TcpSession) -> None:
    raise NotImplementedError


def finalize_upload(session: TcpSession) -> None:
    raise NotImplementedError


def abort_upload(session: TcpSession, reason: str) -> None:
    raise NotImplementedError