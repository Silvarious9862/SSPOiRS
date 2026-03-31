# src/models/udp_single.py
from __future__ import annotations

from typing import NoReturn

from src.utils import logging as log
from src.udp_protocol import create_server_socket, receive_request, handle_datagram


def serve_forever(server_socket) -> None:
    while True:
        received = receive_request(server_socket)
        if received is None:
            continue  # ничего не пришло

        request, client_addr = received
        handle_datagram(server_socket, request, client_addr)


def shutdown_server(server_socket) -> None:
    try:
        server_socket.close()
    finally:
        log.info("UDP single server stopped")


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР1: однопоточный UDP-сервер, обрабатывающий по одному запросу за раз.
    """
    log.set_log_level(log_level)
    log.debug(f"Current log level: {log_level}")

    server_socket = create_server_socket(host, port)
    log.info(f"UDP single server started on {host}:{port}")

    try:
        serve_forever(server_socket)
    except KeyboardInterrupt:
        log.warn("Shutdown requested by Ctrl+C")
    finally:
        shutdown_server(server_socket)

    raise SystemExit(0)