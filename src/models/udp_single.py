# src/models/udp_single.py
from __future__ import annotations

from typing import NoReturn

from src.utils import logging as log
from src.udp_protocol import create_udp_socket, recv_request, UdpEndpoint, handle_datagram


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР2: однопоточный UDP-сервер, обрабатывающий один дейтаграмм за раз.
    """
    # пока только каркас
    raise NotImplementedError("UDP single-thread server is not implemented yet")
