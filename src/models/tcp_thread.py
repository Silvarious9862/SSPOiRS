# src/models/tcp_thread.py
from __future__ import annotations

import threading
from typing import NoReturn

from src.utils import logging as log
from src.tcp_protocol import create_listen_socket, accept_client, handle_client


def _client_worker(client_socket, client_addr) -> None:
    """
    Поток обслуживания одного TCP-клиента.
    Вся логика протокола уже находится в handle_client().
    """
    thread_name = threading.current_thread().name
    log.debug(
        f"[{thread_name}] Started worker for "
        f"{client_addr[0]}:{client_addr[1]}"
    )
    handle_client(client_socket, client_addr)


def serve_forever(server_socket) -> None:
    while True:
        accepted = accept_client(server_socket)
        if accepted is None:
            continue

        client_socket, client_addr = accepted

        worker = threading.Thread(
            target=_client_worker,
            args=(client_socket, client_addr),
            daemon=False,
            name=f"tcp-client-{client_addr[0]}:{client_addr[1]}",
        )
        worker.start()

        log.debug(
            f"Spawned thread {worker.name} for "
            f"{client_addr[0]}:{client_addr[1]}"
        )


def shutdown_server(server_socket) -> None:
    try:
        server_socket.close()
    finally:
        log.info("TCP threaded server stopped")


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР4: многопоточный TCP-сервер.
    Для каждого принятого соединения порождается отдельный поток.
    """
    log.set_log_level(log_level)
    log.debug(f"Current log level: {log_level}")

    server_socket = create_listen_socket(host, port)
    log.info(f"TCP threaded server started on {host}:{port}")

    try:
        serve_forever(server_socket)
    except KeyboardInterrupt:
        log.warn("Shutdown requested by Ctrl+C")
    finally:
        shutdown_server(server_socket)

    raise SystemExit(0)