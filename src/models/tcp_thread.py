# src/models/tcp_thread.py
from __future__ import annotations

import threading
from typing import NoReturn

from src.utils import logging as log
from src.tcp_protocol import create_listen_socket, accept_client, handle_client, TcpConnection


def _client_worker(conn: TcpConnection) -> None:
    """
    Поток для одного клиента.
    Тут будет цикл чтения команд и вызова handle_client / командных хендлеров.
    """
    raise NotImplementedError("TCP client worker thread is not implemented yet")


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР4: многопоточный TCP-сервер.
    Для каждого принятого соединения порождается отдельный поток.
    """
    raise NotImplementedError("TCP threaded server (thread-per-connection) is not implemented yet")