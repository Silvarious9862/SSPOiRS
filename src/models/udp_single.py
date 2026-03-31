from __future__ import annotations

from typing import NoReturn

from src.utils import logging as log
from src.udp_protocol import create_udp_socket, recv_request, UdpEndpoint, handle_datagram


def serve_forever(server_socket) -> None:
    while True:
        received = recv_request(server_socket)
        if received is None:
            continue

        data, client_addr = received
        endpoint = UdpEndpoint(server_socket, client_addr)
        try:
            should_close = handle_datagram(data, endpoint)
            if should_close:
                log.info(f"Client disconnected {client_addr[0]}:{client_addr[1]}")
        except Exception as exc:
            log.error(f"Error while handling {client_addr[0]}:{client_addr[1]}: {exc}")


def shutdown_server(server_socket) -> None:
    try:
        server_socket.close()
    finally:
        log.info("UDP single server stopped")


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    log.set_log_level(log_level)
    log.debug(f"Current log level: {log_level}")
    server_socket = create_udp_socket(host, port)
    log.info(f"UDP single server started on {host}:{port}")

    try:
        serve_forever(server_socket)
    except KeyboardInterrupt:
        log.warn("Shutdown requested by Ctrl+C")
    finally:
        shutdown_server(server_socket)

    raise SystemExit(0)