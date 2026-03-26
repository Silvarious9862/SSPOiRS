# src/tcp_protocol.py
from __future__ import annotations

import socket
from typing import Tuple


class TcpConnection:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int]):
        self.sock = sock
        self.addr = addr

    def recv_line(self) -> str:
        raise NotImplementedError("TcpConnection.recv_line is not implemented yet")

    def send_line(self, data: str) -> None:
        raise NotImplementedError("TcpConnection.send_line is not implemented yet")

    def recv_bytes(self, n: int) -> bytes:
        raise NotImplementedError("TcpConnection.recv_bytes is not implemented yet")

    def send_bytes(self, data: bytes) -> None:
        raise NotImplementedError("TcpConnection.send_bytes is not implemented yet")

    def close(self) -> None:
        raise NotImplementedError("TcpConnection.close is not implemented yet")


def create_listen_socket(host: str, port: int) -> socket.socket:
    """Создаёт TCP-сокет, слушающий host:port."""
    raise NotImplementedError("create_listen_socket is not implemented yet")


def accept_client(listen_sock: socket.socket) -> TcpConnection:
    """Принимает одно соединение и заворачивает его в TcpConnection."""
    raise NotImplementedError("accept_client is not implemented yet")


def handle_client(conn: TcpConnection) -> None:
    """
    Основной цикл обработки команд для одного TCP-клиента.
    Здесь будет парсинг ECHO/TIME/CLOSE/UPLOAD/DOWNLOAD.
    """
    raise NotImplementedError("handle_client is not implemented yet")
