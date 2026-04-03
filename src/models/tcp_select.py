# src/models/tcp_select.py
from __future__ import annotations

import selectors
import socket
from typing import NoReturn

from src.models.tcp_session import create_session
from src.tcp_protocol_select import (
    accept_client,
    close_client,
    create_listen_socket,
    handle_read_ready,
    handle_write_ready,
    queue_hello,
)
from src.utils import logging as log


def register_server(
    selector: selectors.BaseSelector,
    server_socket: socket.socket,
) -> None:
    """Зарегистрировать listening socket в selector."""
    selector.register(server_socket, selectors.EVENT_READ, data=None)


def accept_ready(
    selector: selectors.BaseSelector,
    server_socket: socket.socket,
) -> None:
    """Принять готового клиента и зарегистрировать его сессию."""
    accepted = accept_client(server_socket)
    if accepted is None:
        return

    client_socket, client_addr = accepted
    session = create_session(client_socket, client_addr)

    queue_hello(session)

    selector.register(
        client_socket,
        selectors.EVENT_READ | selectors.EVENT_WRITE,
        data=session,
    )


def service_connection(
    selector: selectors.BaseSelector,
    key: selectors.SelectorKey,
    mask: int,
) -> None:
    """Обслужить одно событие клиентского соединения."""
    session = key.data
    if session is None:
        return

    if mask & selectors.EVENT_READ:
        handle_read_ready(selector, session)

    try:
        current_key = selector.get_key(session.sock)
    except (KeyError, ValueError):
        return

    current_session = current_key.data
    if current_session is None:
        return

    if mask & selectors.EVENT_WRITE:
        handle_write_ready(selector, current_session)


def serve_forever(
    selector: selectors.BaseSelector,
    server_socket: socket.socket,
) -> None:
    """Главный цикл select/poll-сервера."""
    while True:
        events = selector.select(timeout=1.0)

        for key, mask in events:
            if key.data is None:
                accept_ready(selector, key.fileobj)
                continue

            service_connection(selector, key, mask)


def shutdown_server(
    selector: selectors.BaseSelector,
    server_socket: socket.socket,
) -> None:
    """Корректно остановить сервер и закрыть все клиентские сессии."""
    try:
        keys = list(selector.get_map().values())
    except Exception:
        keys = []

    for key in keys:
        if key.data is None:
            continue

        session = key.data
        try:
            close_client(selector, session)
        except Exception as exc:
            log.debug(f"Client shutdown skipped for {session.addr}: {exc}")

    try:
        selector.unregister(server_socket)
    except Exception:
        pass

    try:
        server_socket.close()
    finally:
        try:
            selector.close()
        finally:
            log.info("TCP select server stopped")


def run_server(
    host: str,
    port: int,
    log_level: str = "INFO",
) -> NoReturn:
    """
    ЛР3: TCP-сервер с мультиплексированием в одном потоке.
    """
    log.set_log_level(log_level)
    log.debug(f"Current log level: {log_level}")

    selector = selectors.DefaultSelector()
    server_socket = create_listen_socket(host, port)
    register_server(selector, server_socket)

    log.info(f"TCP select server started on {host}:{port}")

    try:
        serve_forever(selector, server_socket)
    except KeyboardInterrupt:
        log.warn("Shutdown requested by Ctrl+C")
    finally:
        shutdown_server(selector, server_socket)

    raise SystemExit(0)