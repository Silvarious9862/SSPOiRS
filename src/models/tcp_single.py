# src/models/tcp_single.py
from __future__ import annotations

from typing import NoReturn

from src.utils import logging as log
from src.tcp_protocol import create_listen_socket, accept_client, handle_client


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР1: однопоточный TCP-сервер, обслуживающий одного клиента за раз.
    """
    # пока только каркас
    raise NotImplementedError("TCP single-thread server is not implemented yet")
