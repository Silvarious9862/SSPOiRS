# src/handlers_poll/upload.py
from __future__ import annotations

import os
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


def is_upload_command(request: str) -> bool:
    return request.upper().startswith("UPLOAD")


def parse_upload_command(request: str) -> tuple[str, int] | None:
    parts = request.strip().split()
    if len(parts) != 3:
        return None

    _, filename, sizestr = parts

    try:
        total_size = int(sizestr)
    except ValueError:
        return None

    if total_size < 0:
        return None

    return filename, total_size


def sanitize_upload_filename(filename: str) -> str:
    return os.path.basename(filename.strip())


def _queue_raw_line(session: TcpSession, message: str) -> None:
    session.out_buffer.extend(f"{message}\n".encode("utf-8"))


def _get_remaining(session: TcpSession) -> int:
    return session.current_filesize - session.current_offset - session.bytes_done


def prepare_upload(session: TcpSession, filename: str, total_size: int) -> None:
    safe_name = sanitize_upload_filename(filename)
    os.makedirs(BASEDIR, exist_ok=True)
    path = os.path.join(BASEDIR, safe_name)

    offset = 0
    if os.path.exists(path):
        try:
            offset = os.path.getsize(path)
        except OSError:
            offset = 0

    if offset > total_size:
        offset = 0

    remaining = total_size - offset
    mode = "ab" if offset > 0 else "wb"

    try:
        file_obj = open(path, mode)
    except OSError as exc:
        log.error(f"Cannot open file for upload {path}: {exc}")
        _queue_raw_line(session, "ERROR cannot write file")
        return

    close_session_file(session)
    session.current_file = file_obj

    start_transfer(
        session,
        kind="upload",
        filename=safe_name,
        filesize=total_size,
        offset=offset,
    )

    if offset > 0:
        _queue_raw_line(session, f"RESUME {offset}")
    else:
        _queue_raw_line(session, "OK READY")

    if remaining == 0:
        finalize_upload(session)
        return

    log.debug(
        f"Starting nonblocking upload file={safe_name}, "
        f"total={total_size}, offset={offset}, remaining={remaining}"
    )


def handle_upload_start(session: TcpSession, request: str) -> None:
    parsed = parse_upload_command(request)
    if parsed is None:
        _queue_raw_line(session, "ERROR invalid UPLOAD syntax")
        return

    filename, total_size = parsed
    prepare_upload(session, filename, total_size)


def continue_upload_receive(session: TcpSession) -> None:
    if session.transfer_kind != "upload":
        return

    if session.current_file is None:
        abort_upload(session, "ERROR internal upload state")
        return

    remaining = _get_remaining(session)
    if remaining <= 0:
        finalize_upload(session)
        return

    try:
        chunk = session.sock.recv(min(BUFFERSIZE, remaining))
    except BlockingIOError:
        return
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        log.debug(f"Connection error during upload recv from {session.addr}: {exc}")
        raise

    if not chunk:
        abort_upload(
            session,
            f"ERROR upload interrupted at "
            f"{session.current_offset + session.bytes_done} "
            f"of {session.current_filesize} bytes",
        )
        return

    try:
        session.current_file.write(chunk)
        session.current_file.flush()
    except OSError as exc:
        log.error(f"File write error for {session.current_filename}: {exc}")
        abort_upload(session, "ERROR cannot write file")
        return

    session.bytes_done += len(chunk)

    expected = session.current_filesize - session.current_offset
    if expected > 0:
        percent = int(session.bytes_done * 100 / expected)
        step = percent // OOB_PROGRESS_STEP

        if step > session.last_progress_step:
            log_percent = min(step * OOB_PROGRESS_STEP, 100)
            log.debug(
                f"UPLOAD received regular bytes: {session.bytes_done}/{expected} "
                f"({log_percent}%) for {session.addr}"
            )
            session.last_progress_step = step

    if _get_remaining(session) <= 0:
        finalize_upload(session)


def finalize_upload(session: TcpSession) -> None:
    expected = session.current_filesize - session.current_offset
    received = session.bytes_done
    duration = get_transfer_elapsed(session)

    close_session_file(session)

    if received == expected and expected >= 0:
        speed_kbps = received / 1024 / duration if duration > 0 else 0.0
        log.info(f"UPLOAD finished for {session.addr}, bytes={received}")
        _queue_raw_line(
            session,
            f"OK UPLOADED {session.current_filesize} bytes in "
            f"{duration:.3f} s, {speed_kbps:.2f} KB/s",
        )
    else:
        _queue_raw_line(
            session,
            f"ERROR upload interrupted at "
            f"{session.current_offset + session.bytes_done} "
            f"of {session.current_filesize} bytes",
        )

    reset_transfer_state(session)


def abort_upload(session: TcpSession, reason: str) -> None:
    log.debug(
        f"Upload aborted for {session.addr}: {reason}; "
        f"done={session.current_offset + session.bytes_done}/"
        f"{session.current_filesize}"
    )
    close_session_file(session)
    _queue_raw_line(session, reason)
    reset_transfer_state(session)