# src/models/tcp_select.py
from __future__ import annotations

import select
from typing import NoReturn

from src.utils import logging as log
from src.tcp_protocol import create_listen_socket, accept_client, handle_client, TcpConnection


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР3: однопоточный TCP-сервер с мультиплексированием клиентов
    (select/pselect/poll) в рамках одного потока.
    """
    raise NotImplementedError("TCP multiplexing server (select) is not implemented yet")
