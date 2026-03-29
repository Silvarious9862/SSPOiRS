# src/models/tcp_single.py
from __future__ import annotations

from typing import NoReturn

from src.utils import logging as log
from src.tcp_protocol import create_listen_socket, accept_client, handle_client


def serve_forever(server_socket) -> None:
    while True:
        accepted = accept_client(server_socket)
        if accepted is None:
            continue  # ничего не пришло

        client_socket, client_addr = accepted
        handle_client(client_socket, client_addr)

def shutdown_server(server_socket) -> None:
    try:
        server_socket.close()
    finally:
        log.info("TCP single server stopped")

def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР1: однопоточный TCP-сервер, обслуживающий одного клиента за раз.
    """
    log.set_log_level(log_level)
    server_socket = create_listen_socket(host, port)
    log.info(f"TCP single server started on {host}:{port}")

    try:
        serve_forever(server_socket)
    except KeyboardInterrupt:
        log.warn("Shutdown requested by Ctrl+C")
    finally:
        shutdown_server(server_socket)

    raise SystemExit(0)