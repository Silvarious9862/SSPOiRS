# src/handlers_poll/download.py
from __future__ import annotations

import os
import socket
from typing import Final

from src.models.tcp_session import (
    TcpSession,
    close_session_file,
    get_transfer_elapsed,
    reset_transfer_state,
    start_transfer,
)
from src.utils import logging as log

BUFFERSIZE: Final[int] = 4096
BASEDIR: Final[str] = "serverfiles"
OOB_PROGRESS_STEP: Final[int] = 10


def is_download_command(request: str) -> bool:
    return request.upper().startswith("DOWNLOAD")


def parse_download_command(request: str) -> tuple[str, int] | None:
    parts = request.strip().split()
    if len(parts) not in (2, 3):
        return None

    _, filename, *rest = parts
    offset = 0

    if rest:
        try:
            offset = int(rest[0])
        except ValueError:
            return None
        if offset < 0:
            return None

    return filename, offset


def sanitize_download_filename(filename: str) -> str:
    return os.path.basename(filename.strip())


def _queue_raw_line(session: TcpSession, message: str) -> None:
    session.out_buffer.extend(f"{message}\n".encode("utf-8"))


def _send_oob_progress(session: TcpSession, percent: int) -> None:
    try:
        session.sock.send(bytes([percent]), socket.MSG_OOB)
    except (BrokenPipeError, ConnectionResetError, OSError, ValueError) as exc:
        log.debug(f"OOB send skipped for {session.addr}: {exc}")


def _get_remaining(session: TcpSession) -> int:
    return session.current_filesize - session.current_offset - session.bytes_done


def prepare_download(session: TcpSession, filename: str, offset: int) -> None:
    safe_name = sanitize_download_filename(filename)
    path = os.path.join(BASEDIR, safe_name)

    if not os.path.exists(path):
        _queue_raw_line(session, "ERROR file not found")
        return

    try:
        filesize = os.path.getsize(path)
    except OSError as exc:
        log.error(f"Cannot stat file {path}: {exc}")
        _queue_raw_line(session, "ERROR cannot read file")
        return

    if offset > filesize:
        _queue_raw_line(session, "ERROR invalid offset")
        return

    remaining = filesize - offset

    if remaining == 0:
        _queue_raw_line(session, "OK 0")
        _queue_raw_line(
            session,
            f"OK DOWNLOADED {filesize} bytes in 0.000 s, 0.00 KB/s",
        )
        return

    try:
        file_obj = open(path, "rb")
        file_obj.seek(offset)
    except OSError as exc:
        log.error(f"Cannot open file {path}: {exc}")
        _queue_raw_line(session, "ERROR cannot read file")
        return

    close_session_file(session)
    session.current_file = file_obj

    start_transfer(
        session,
        kind="download",
        filename=safe_name,
        filesize=filesize,
        offset=offset,
    )

    _queue_raw_line(session, f"OK {remaining}")

    log.debug(
        f"Starting nonblocking download file={safe_name}, "
        f"size={filesize}, offset={offset}, remaining={remaining}"
    )


def handle_download_start(session: TcpSession, request: str) -> None:
    parsed = parse_download_command(request)
    if parsed is None:
        _queue_raw_line(session, "ERROR invalid DOWNLOAD syntax")
        return

    filename, offset = parsed
    prepare_download(session, filename, offset)


def continue_download_send(session: TcpSession) -> None:
    if session.transfer_kind != "download":
        return

    if session.current_file is None:
        abort_download(session, "ERROR internal download state")
        return

    if session.out_buffer:
        return

    remaining = _get_remaining(session)
    if remaining <= 0:
        finalize_download(session)
        return

    try:
        chunk = session.current_file.read(min(BUFFERSIZE, remaining))
    except OSError as exc:
        log.error(f"File read error for {session.current_filename}: {exc}")
        abort_download(session, "ERROR cannot read file")
        return

    if not chunk:
        abort_download(session, "ERROR download interrupted")
        return

    session.out_buffer.extend(chunk)
    session.bytes_done += len(chunk)

    expected = session.current_filesize - session.current_offset
    if expected > 0:
        percent = int(session.bytes_done * 100 / expected)
        step = percent // OOB_PROGRESS_STEP

        if step > session.last_progress_step and percent < 100:
            oob_percent = min(step * OOB_PROGRESS_STEP, 99)
            _send_oob_progress(session, oob_percent)
            session.last_progress_step = step

            log.debug(
                f"DOWNLOAD sent regular bytes: {session.bytes_done}/{expected} "
                f"({oob_percent}%) for {session.addr}"
            )

    if _get_remaining(session) <= 0 and not session.out_buffer:
        finalize_download(session)


def finalize_download(session: TcpSession) -> None:
    expected = session.current_filesize - session.current_offset
    sent = session.bytes_done
    duration = get_transfer_elapsed(session)

    close_session_file(session)

    if sent == expected and expected >= 0:
        _send_oob_progress(session, 100)
        speed_kbps = sent / 1024 / duration if duration > 0 else 0.0

        log.info(f"DOWNLOAD finished for {session.addr}, bytes={sent}")
        _queue_raw_line(
            session,
            f"OK DOWNLOADED {session.current_filesize} bytes in "
            f"{duration:.3f} s, {speed_kbps:.2f} KB/s",
        )
    else:
        _queue_raw_line(
            session,
            f"ERROR download interrupted at offset "
            f"{session.current_offset + session.bytes_done} "
            f"of {session.current_filesize} bytes",
        )

    reset_transfer_state(session)


def abort_download(session: TcpSession, reason: str) -> None:
    log.debug(
        f"Download aborted for {session.addr}: {reason}; "
        f"done={session.current_offset + session.bytes_done}/"
        f"{session.current_filesize}"
    )
    close_session_file(session)
    _queue_raw_line(session, reason)
    reset_transfer_state(session)