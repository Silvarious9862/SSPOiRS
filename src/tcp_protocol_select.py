# src/tcp_protocol_select.py
from __future__ import annotations

import selectors
import socket
from typing import Final

from src.handlers_select import (
    continue_download_send,
    continue_upload_receive,
    handle_close,
    handle_download_start,
    handle_echo,
    handle_time,
    handle_upload_start,
    is_close_command,
    is_download_command,
    is_echo_command,
    is_time_command,
    is_upload_command,
)
from src.models.tcp_session import (
    TcpSession,
    close_session_file,
    create_session,
    mark_session_closing,
)
from src.utils import logging as log
from src.utils.colors import colorize

BUFFERSIZE: Final[int] = 4096
BACKLOG: Final[int] = 5

KEEPALIVE_IDLE: Final[int] = 15
KEEPALIVE_INTVL: Final[int] = 5
KEEPALIVE_CNT: Final[int] = 4


def apply_keepalive(sock: socket.socket) -> None:
    """Включить SO_KEEPALIVE на сокете кроссплатформенно."""
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
    """Создать неблокирующий listening socket."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(BACKLOG)
    server_socket.setblocking(False)
    return server_socket


def accept_client(
    server_socket: socket.socket,
) -> tuple[socket.socket, tuple[str, int]] | None:
    """Принять клиента с неблокирующего server socket."""
    try:
        client_socket, client_addr = server_socket.accept()
    except BlockingIOError:
        return None

    client_socket.setblocking(False)
    apply_keepalive(client_socket)
    log.info(f"Client connected {client_addr[0]}:{client_addr[1]}")
    return client_socket, client_addr


def queue_bytes(session: TcpSession, data: bytes) -> None:
    """Добавить байты в выходной буфер сессии."""
    if not data:
        return
    session.out_buffer.extend(data)


def queue_line(
    session: TcpSession,
    message: str,
    *,
    level: str = "info",
) -> None:
    """Добавить строковый ответ в выходной буфер."""
    colored = colorize(message, level=level)
    queue_bytes(session, f"{colored}\n".encode("utf-8"))
    log.debug(f"Sent to {session.addr[0]}:{session.addr[1]}: {message!r}")


def queue_hello(session: TcpSession) -> None:
    """Поставить приветственное сообщение клиенту."""
    queue_line(session, "HELLO", level="info")


def extract_lines(session: TcpSession) -> list[str]:
    """
    Извлечь завершенные строковые команды из входного буфера.
    Обрабатываем только режим line; бинарные данные upload здесь не трогаем.
    """
    if session.command_mode != "line":
        return []

    lines: list[str] = []

    while True:
        pos = session.in_buffer.find(b"\n")
        if pos < 0:
            break

        raw = bytes(session.in_buffer[: pos + 1])
        del session.in_buffer[: pos + 1]

        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        lines.append(line)

    return lines


def process_line(session: TcpSession, line: str) -> None:
    """Обработать одну строку команды."""
    request = line.strip()

    if not request:
        queue_line(session, "ERROR empty request", level="error")
        return

    log.debug(f"Received from {session.addr[0]}:{session.addr[1]}: {request!r}")
    dispatch_command(session, request)


def dispatch_command(session: TcpSession, request: str) -> None:
    """Маршрутизация команд протокола."""
    if not request:
        queue_line(session, "ERROR empty request", level="error")
        return

    if is_close_command(request):
        handle_close(session, request)
        return

    if is_echo_command(request):
        handle_echo(session, request)
        return

    if is_time_command(request):
        handle_time(session, request)
        return

    if is_upload_command(request):
        handle_upload_start(session, request)
        return

    if is_download_command(request):
        handle_download_start(session, request)
        return

    queue_line(session, "ERROR unknown command", level="error")


def handle_read_ready(
    selector: selectors.BaseSelector,
    session: TcpSession,
) -> None:
    """Обработать готовность сокета к чтению."""
    if session.sock.fileno() == -1:
            return
    
    if session.command_mode == "upload":
        try:
            continue_upload_receive(session)
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            log.debug(f"Read error from {session.addr}: {exc}")
            close_client(selector, session)
            return

        if session.sock.fileno() == -1:
                return

        update_interest(selector, session)
        return
    
    try:
        data = session.sock.recv(BUFFERSIZE)
    except BlockingIOError:
        return
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        log.debug(f"Read error from {session.addr}: {exc}")
        close_client(selector, session)
        return

    if not data:
        close_client(selector, session)
        return

    session.in_buffer.extend(data)

    for line in extract_lines(session):
        process_line(session, line)

    update_interest(selector, session)


def handle_write_ready(
    selector: selectors.BaseSelector,
    session: TcpSession,
) -> None:
    flush_out_buffer(selector, session)

    if session.sock.fileno() == -1:
        return

    if session.command_mode == "download" and not session.out_buffer:
        continue_download_send(session)
        flush_out_buffer(selector, session)
        if session.sock.fileno() == -1:
            return

    if session.closing and not session.out_buffer and session.command_mode == "line":
        close_client(selector, session)
        return

    update_interest(selector, session)


def flush_out_buffer(
    selector: selectors.BaseSelector,
    session: TcpSession,
) -> None:
    """Попытаться отправить накопленный выходной буфер."""
    if not session.out_buffer:
        return

    try:
        sent = session.sock.send(session.out_buffer)
    except BlockingIOError:
        return
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        log.debug(f"Write error to {session.addr}: {exc}")
        close_client(selector, session)
        return

    if sent > 0:
        '''preview = session.out_buffer[:sent]
        # Попробуем распознать как текст, не ломая бинарные данные
        try:
            text = preview.decode("utf-8", errors="ignore").strip()
        except Exception:
            text = ""
        if text:
            log.debug(f"Sent {sent} bytes to {session.addr}: {text!r}")
        else:
            log.debug(f"Sent {sent} bytes to {session.addr} (binary)")'''
        del session.out_buffer[:sent]


def update_interest(
    selector: selectors.BaseSelector,
    session: TcpSession,
) -> None:
    """Обновить интересующие события selector для клиентского сокета."""
    events = selectors.EVENT_READ

    if session.out_buffer or session.command_mode == "download":
        events |= selectors.EVENT_WRITE

    try:
        selector.modify(session.sock, events, data=session)
    except KeyError:
        return
    except OSError as exc:
        log.debug(f"Selector modify failed for {session.addr}: {exc}")
        close_client(selector, session)


def close_client(
    selector: selectors.BaseSelector,
    session: TcpSession,
) -> None:
    """Снять клиента с selector и закрыть сокет/файл сессии."""
    close_session_file(session)

    try:
        selector.unregister(session.sock)
    except Exception:
        pass

    try:
        session.sock.close()
    finally:
        log.info(f"Client disconnected {session.addr[0]}:{session.addr[1]}")