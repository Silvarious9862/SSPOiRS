# src/udp_protocol.py
from __future__ import annotations

import socket
from typing import Tuple


class UdpEndpoint:
    """
    Обёртка над UDP-сокетом + адрес клиента.
    Нужна, чтобы интерфейс был похож на TcpConnection.
    """

    def __init__(self, sock: socket.socket, addr: Tuple[str, int]):
        self.sock = sock
        self.addr = addr

    def send_line(self, data: str) -> None:
        raise NotImplementedError("UdpEndpoint.send_line is not implemented yet")

    def send_bytes(self, data: bytes) -> None:
        raise NotImplementedError("UdpEndpoint.send_bytes is not implemented yet")


def create_udp_socket(host: str, port: int) -> socket.socket:
    """Создаёт и биндует UDP-сокет на host:port."""
    raise NotImplementedError("create_udp_socket is not implemented yet")


def recv_request(sock: socket.socket) -> Tuple[bytes, Tuple[str, int]]:
    """
    Получает один UDP-дейтаграмм.
    Возвращает (raw_data, client_addr).
    """
    raise NotImplementedError("recv_request is not implemented yet")


def handle_datagram(data: bytes, endpoint: UdpEndpoint) -> None:
    """
    Обработка одной команды по UDP.
    Здесь позже будет парсинг ECHO/TIME/CLOSE/UPLOAD/DOWNLOAD.
    """
    raise NotImplementedError("handle_datagram is not implemented yet")
