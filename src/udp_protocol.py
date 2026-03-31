from __future__ import annotations

import socket
import struct
import time
from datetime import datetime
from typing import Final

from src.utils import logging as log
from src.utils.colors import colorize
from src.utils.files import load_bytes, save_bytes

BUFFERSIZE: Final[int] = 65535
SOCKET_TIMEOUT: Final[float] = 0.5
CHUNK_SIZE: Final[int] = 8192
ACK_EVERY: Final[int] = 32
ACK_TIMEOUT: Final[float] = 0.3
WINDOW_SIZE: Final[int] = 128
MAX_RETRIES: Final[int] = 30
SESSION_IDLE_TIMEOUT: Final[float] = 120.0

PKT_DATA: Final[int] = 0x03
PKT_ACK: Final[int] = 0x04
PKT_NACK: Final[int] = 0x05
PKT_FIN: Final[int] = 0x06

SESSION_NEW: Final[str] = "NEW"
SESSION_ACTIVE: Final[str] = "ACTIVE"
SESSION_CLOSED: Final[str] = "CLOSED"

_HDR_DATA = struct.Struct("!BIIH")
_HDR_ACK = struct.Struct("!BI")
_HDR_FIN = struct.Struct("!BII")

_sessions: dict[tuple[str, int], dict[str, object]] = {}


def _touch_session(addr: tuple[str, int]) -> dict[str, object]:
    now = time.monotonic()
    state = _sessions.get(addr)
    if state is None:
        state = {"state": SESSION_NEW, "updated_at": now}
        _sessions[addr] = state
    else:
        state["updated_at"] = now
    return state


def _expire_sessions() -> None:
    now = time.monotonic()
    expired = [
        addr
        for addr, state in _sessions.items()
        if now - float(state.get("updated_at", now)) > SESSION_IDLE_TIMEOUT
    ]
    for addr in expired:
        _sessions.pop(addr, None)
        log.debug(f"UDP session expired for {addr[0]}:{addr[1]}")


def _get_session_state(addr: tuple[str, int]) -> str:
    _expire_sessions()
    session = _touch_session(addr)
    return str(session["state"])


def _set_session_state(addr: tuple[str, int], state: str) -> None:
    session = _touch_session(addr)
    session["state"] = state


def _last_contiguous_seq(received: dict[int, bytes]) -> int:
    seq = 0
    while seq in received:
        seq += 1
    return seq - 1


class UdpEndpoint:
    def __init__(self, sock: socket.socket, addr: tuple[str, int]):
        self.sock = sock
        self.addr = addr

    def send_line(self, data: str, *, level: str = "info") -> None:
        colored = colorize(data, level=level)
        self.sock.sendto(f"{colored}\n".encode("utf-8"), self.addr)
        log.debug(f"Sent to {self.addr}: {data!r}")

    def send_ack(self, seq: int) -> None:
        self.sock.sendto(_HDR_ACK.pack(PKT_ACK, seq), self.addr)

    def send_nack(self, seq: int) -> None:
        self.sock.sendto(_HDR_ACK.pack(PKT_NACK, seq), self.addr)

    def send_file(self, data: bytes) -> float:
        chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)] or [b""]
        total = len(chunks)
        packets = {
            seq: _HDR_DATA.pack(PKT_DATA, seq, total, len(chunk)) + chunk
            for seq, chunk in enumerate(chunks)
        }

        base = 0
        next_seq = 0
        window: dict[int, bytes] = {}
        retries: dict[int, int] = {}
        started = time.monotonic()
        self.sock.settimeout(ACK_TIMEOUT)

        while base < total:
            while next_seq < min(base + WINDOW_SIZE, total):
                packet = packets[next_seq]
                self.sock.sendto(packet, self.addr)
                window[next_seq] = packet
                retries.setdefault(next_seq, 0)
                next_seq += 1

            try:
                packet, addr = self.sock.recvfrom(BUFFERSIZE)
            except (socket.timeout, TimeoutError):
                if base == 0 or base % 512 == 0:
                    log.warn(f"ACK timeout from {self.addr}, retransmitting from seq={base}")
                for seq in sorted(window):
                    retries[seq] += 1
                    if retries[seq] > MAX_RETRIES:
                        raise ConnectionError(f"No ACK for seq={seq} after {MAX_RETRIES} retries")
                    self.sock.sendto(window[seq], self.addr)
                continue
            except OSError as exc:
                raise ConnectionError(f"Network send error: {exc}") from exc

            if addr != self.addr or len(packet) < _HDR_ACK.size:
                continue

            kind, seq = _HDR_ACK.unpack(packet[:_HDR_ACK.size])
            if kind == PKT_ACK:
                if seq >= base:
                    for confirmed in range(base, seq + 1):
                        window.pop(confirmed, None)
                    base = seq + 1
            elif kind == PKT_NACK and seq in window:
                self.sock.sendto(window[seq], self.addr)

        checksum = sum(range(total)) & 0xFFFFFFFF
        fin_packet = _HDR_FIN.pack(PKT_FIN, total, checksum)
        for _ in range(MAX_RETRIES):
            self.sock.sendto(fin_packet, self.addr)
            try:
                packet, addr = self.sock.recvfrom(BUFFERSIZE)
            except (socket.timeout, TimeoutError):
                continue
            except OSError as exc:
                raise ConnectionError(f"Network FIN error: {exc}") from exc
            if addr != self.addr or len(packet) < _HDR_ACK.size:
                continue
            kind, seq = _HDR_ACK.unpack(packet[:_HDR_ACK.size])
            if kind == PKT_ACK and seq >= total - 1:
                break
        else:
            raise ConnectionError("FIN not acknowledged")

        elapsed = time.monotonic() - started
        return len(data) / elapsed if elapsed > 0 else 0.0

    def recv_file(self) -> tuple[bytes, float]:
        received: dict[int, bytes] = {}
        total_chunks: int | None = None
        ack_counter = 0
        last_acked = -1
        started = time.monotonic()
        self.sock.settimeout(ACK_TIMEOUT * 5)

        while True:
            try:
                packet, addr = self.sock.recvfrom(BUFFERSIZE)
            except (socket.timeout, TimeoutError):
                raise ConnectionError("Timeout waiting for UDP data")
            except OSError as exc:
                raise ConnectionError(f"Network recv error: {exc}") from exc

            if addr != self.addr or not packet:
                continue

            ptype = packet[0]
            if ptype == PKT_DATA:
                if len(packet) < _HDR_DATA.size:
                    continue
                _, seq, total, chunk_len = _HDR_DATA.unpack(packet[:_HDR_DATA.size])
                payload = packet[_HDR_DATA.size:_HDR_DATA.size + chunk_len]
                total_chunks = total
                if seq not in received:
                    received[seq] = payload
                    ack_counter += 1

                contiguous = _last_contiguous_seq(received)
                should_ack = False
                if contiguous > last_acked and ack_counter >= ACK_EVERY:
                    should_ack = True
                if total_chunks is not None and contiguous == total_chunks - 1:
                    should_ack = True

                if should_ack:
                    self.send_ack(contiguous)
                    last_acked = contiguous
                    ack_counter = 0

            elif ptype == PKT_FIN:
                if len(packet) < _HDR_FIN.size:
                    continue
                _, total, _ = _HDR_FIN.unpack(packet[:_HDR_FIN.size])
                total_chunks = total
                missing = [i for i in range(total) if i not in received]
                if missing:
                    self.send_nack(missing[0])
                    continue
                self.send_ack(total - 1)
                break

        if total_chunks is None:
            raise ConnectionError("Transfer finished without metadata")

        data = b"".join(received[i] for i in range(total_chunks))
        elapsed = time.monotonic() - started
        return data, (len(data) / elapsed if elapsed > 0 else 0.0)


def create_udp_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
    sock.bind((host, port))
    sock.settimeout(SOCKET_TIMEOUT)
    return sock


def recv_request(sock: socket.socket) -> tuple[bytes, tuple[str, int]] | None:
    try:
        return sock.recvfrom(BUFFERSIZE)
    except (socket.timeout, TimeoutError):
        return None


def _decode_text_command(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return text or None


def build_text_response(request: str) -> tuple[str, str, bool]:
    req = request.strip()
    low = req.lower()
    if low == "close":
        return "BYE", "info", True
    if low == "time":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "info", False
    if low.startswith("echo "):
        return req[5:], "info", False
    return "ERROR unknown command", "error", False


def handle_datagram(data: bytes, endpoint: UdpEndpoint) -> bool:
    request = _decode_text_command(data)
    if request is None:
        log.debug(f"Ignored non-text UDP datagram from {endpoint.addr}")
        return False

    state = _get_session_state(endpoint.addr)
    log.debug(f"Received from {endpoint.addr}: {request!r} [session={state}]")
    low = request.lower()

    if low == "hello":
        _set_session_state(endpoint.addr, SESSION_ACTIVE)
        endpoint.send_line("HELLO")
        log.info(f"UDP session started for {endpoint.addr[0]}:{endpoint.addr[1]}")
        return False

    if state == SESSION_NEW:
        endpoint.send_line("ERROR send HELLO first", level="error")
        return False

    if state == SESSION_CLOSED:
        endpoint.send_line("ERROR session closed, send HELLO to start again", level="error")
        return False

    if low.startswith("upload "):
        return _handle_upload(request, endpoint)
    if low.startswith("download "):
        return _handle_download(request, endpoint)

    response, level, should_close = build_text_response(request)
    endpoint.send_line(response, level=level)
    if should_close:
        _set_session_state(endpoint.addr, SESSION_CLOSED)
        log.info(f"UDP session closed for {endpoint.addr[0]}:{endpoint.addr[1]}")
    return should_close


def _handle_upload(request: str, endpoint: UdpEndpoint) -> bool:
    parts = request.split(maxsplit=2)
    if len(parts) != 3:
        endpoint.send_line("ERROR usage: upload <filename> <size>", level="error")
        return False

    _, filename, size_raw = parts
    try:
        expected_size = int(size_raw)
        if expected_size < 0:
            raise ValueError
    except ValueError:
        endpoint.send_line("ERROR invalid file size", level="error")
        return False

    endpoint.send_line(f"OK READY {filename}")
    log.info(f"UDP upload started from {endpoint.addr}: {filename} ({expected_size} bytes)")

    try:
        data, bitrate = endpoint.recv_file()
    except ConnectionError as exc:
        log.error(f"UDP upload failed from {endpoint.addr}: {exc}")
        endpoint.send_line(f"ERROR upload failed: {exc}", level="error")
        return False

    if len(data) != expected_size:
        log.warn(
            f"UDP upload size mismatch from {endpoint.addr}: expected={expected_size}, got={len(data)}"
        )

    path = save_bytes(filename, data)
    kbps = bitrate * 8 / 1024
    log.info(
        f"UDP upload completed from {endpoint.addr}: {path.name}, {len(data)} bytes, bitrate={kbps:.1f} kbps"
    )
    endpoint.send_line(f"OK UPLOADED {path.name} {len(data)} bytes {kbps:.1f} kbps")
    return False


def _handle_download(request: str, endpoint: UdpEndpoint) -> bool:
    parts = request.split(maxsplit=1)
    if len(parts) != 2:
        endpoint.send_line("ERROR usage: download <filename>", level="error")
        return False

    _, filename = parts
    try:
        data, size = load_bytes(filename)
    except FileNotFoundError:
        endpoint.send_line("ERROR file not found", level="error")
        return False

    endpoint.send_line(f"OK {size}")
    log.info(f"UDP download started for {endpoint.addr}: {filename} ({size} bytes)")

    try:
        bitrate = endpoint.send_file(data)
    except ConnectionError as exc:
        log.error(f"UDP download failed to {endpoint.addr}: {exc}")
        return False

    kbps = bitrate * 8 / 1024
    log.info(
        f"UDP download completed for {endpoint.addr}: {filename}, {size} bytes, bitrate={kbps:.1f} kbps"
    )
    endpoint.send_line(f"OK DOWNLOADED {filename} {size} bytes {kbps:.1f} kbps")
    return False