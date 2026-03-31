from __future__ import annotations

import argparse
import re
import socket
import struct
import time
from pathlib import Path
from typing import Final

HOST: Final[str] = "127.0.0.1"
PORT: Final[int] = 5001
BUFFERSIZE: Final[int] = 65535

CHUNK_SIZE: Final[int] = 8192
ACK_EVERY: Final[int] = 32
ACK_TIMEOUT: Final[float] = 0.3
WINDOW_SIZE: Final[int] = 128
MAX_RETRIES: Final[int] = 30
CONTROL_TIMEOUT: Final[float] = 3.0
FINAL_TIMEOUT: Final[float] = 10.0

PKT_DATA: Final[int] = 0x03
PKT_ACK: Final[int] = 0x04
PKT_NACK: Final[int] = 0x05
PKT_FIN: Final[int] = 0x06

_HDR_DATA = struct.Struct("!BIIH")
_HDR_ACK = struct.Struct("!BI")
_HDR_FIN = struct.Struct("!BII")
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def last_contiguous_seq(received: dict[int, bytes]) -> int:
    seq = 0
    while seq in received:
        seq += 1
    return seq - 1


class UdpClient:
    def __init__(self, host: str, port: int):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        self.sock.settimeout(CONTROL_TIMEOUT)
        self.session_active = False

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def recv_text(self, timeout: float = CONTROL_TIMEOUT) -> str | None:
        self.sock.settimeout(timeout)
        try:
            data, _ = self.sock.recvfrom(BUFFERSIZE)
        except (socket.timeout, TimeoutError):
            return None
        except OSError:
            return None
        return strip_ansi(data.decode("utf-8", errors="replace").strip())

    def send_text(self, text: str, timeout: float = CONTROL_TIMEOUT) -> str | None:
        try:
            self.sock.sendto((text.strip() + "\n").encode("utf-8"), self.addr)
        except OSError:
            return None
        response = self.recv_text(timeout)
        command = text.strip().lower()
        if command == "hello" and response == "HELLO":
            self.session_active = True
        elif command == "close" and response == "BYE":
            self.session_active = False
        return response

    def ensure_session(self) -> bool:
        if self.session_active:
            return True
        response = self.send_text("hello")
        if response != "HELLO":
            print(f"[ERROR] Cannot start UDP session: {response!r}")
            return False
        print(f"[SERVER] {response}")
        return True

    def upload(self, filepath: str) -> None:
        if not self.ensure_session():
            return

        path = Path(filepath)
        if not path.exists() or not path.is_file():
            print(f"[ERROR] Local file not found: {filepath}")
            return

        data = path.read_bytes()
        response = self.send_text(f"upload {path.name} {len(data)}")
        if response is None:
            print("[ERROR] No response from server")
            return
        print(f"[SERVER] {response}")
        if not response.startswith("OK READY"):
            return

        started = time.monotonic()
        try:
            bitrate = self._send_file(data)
        except ConnectionError as exc:
            print(f"[ERROR] Upload failed: {exc}")
            return

        final = self.recv_text(FINAL_TIMEOUT)
        if final:
            print(f"[SERVER] {final}")
        elapsed = time.monotonic() - started
        print(f"[INFO] Upload bitrate: {bitrate * 8 / 1024:.1f} kbps, elapsed={elapsed:.3f}s")

    def download(self, filename: str) -> None:
        if not self.ensure_session():
            return

        response = self.send_text(f"download {filename}")
        if response is None:
            print("[ERROR] No response from server")
            return
        print(f"[SERVER] {response}")
        if not response.startswith("OK "):
            return

        started = time.monotonic()
        try:
            data, bitrate = self._recv_file()
        except ConnectionError as exc:
            print(f"[ERROR] Download failed: {exc}")
            return

        Path(filename).write_bytes(data)
        final = self.recv_text(FINAL_TIMEOUT)
        if final:
            print(f"[SERVER] {final}")
        elapsed = time.monotonic() - started
        print(f"[INFO] Download bitrate: {bitrate * 8 / 1024:.1f} kbps, elapsed={elapsed:.3f}s")

    def _send_file(self, data: bytes) -> float:
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
                packet, _ = self.sock.recvfrom(BUFFERSIZE)
            except (socket.timeout, TimeoutError):
                for seq in sorted(window):
                    retries[seq] += 1
                    if retries[seq] > MAX_RETRIES:
                        raise ConnectionError(f"No ACK for seq={seq} after {MAX_RETRIES} retries")
                    self.sock.sendto(window[seq], self.addr)
                continue
            except OSError as exc:
                raise ConnectionError(f"Network send error: {exc}") from exc

            if len(packet) < _HDR_ACK.size:
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
                packet, _ = self.sock.recvfrom(BUFFERSIZE)
            except (socket.timeout, TimeoutError):
                continue
            except OSError as exc:
                raise ConnectionError(f"Network FIN error: {exc}") from exc
            if len(packet) < _HDR_ACK.size:
                continue
            kind, seq = _HDR_ACK.unpack(packet[:_HDR_ACK.size])
            if kind == PKT_ACK and seq >= total - 1:
                break
        else:
            raise ConnectionError("FIN not acknowledged")

        elapsed = time.monotonic() - started
        return len(data) / elapsed if elapsed > 0 else 0.0

    def _recv_file(self) -> tuple[bytes, float]:
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

            if not packet:
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

                contiguous = last_contiguous_seq(received)
                should_ack = False
                if contiguous > last_acked and ack_counter >= ACK_EVERY:
                    should_ack = True
                if total_chunks is not None and contiguous == total_chunks - 1:
                    should_ack = True

                if should_ack:
                    self.sock.sendto(_HDR_ACK.pack(PKT_ACK, contiguous), addr)
                    last_acked = contiguous
                    ack_counter = 0

            elif ptype == PKT_FIN:
                if len(packet) < _HDR_FIN.size:
                    continue
                _, total, _ = _HDR_FIN.unpack(packet[:_HDR_FIN.size])
                total_chunks = total
                missing = [i for i in range(total) if i not in received]
                if missing:
                    self.sock.sendto(_HDR_ACK.pack(PKT_NACK, missing[0]), addr)
                    continue
                self.sock.sendto(_HDR_ACK.pack(PKT_ACK, total - 1), addr)
                break

        if total_chunks is None:
            raise ConnectionError("Missing transfer metadata")

        data = b"".join(received[i] for i in range(total_chunks))
        elapsed = time.monotonic() - started
        return data, (len(data) / elapsed if elapsed > 0 else 0.0)


def interactive_client(host: str, port: int) -> None:
    client = UdpClient(host, port)
    print(f"UDP Client connecting to {host}:{port}")
    print("Commands: hello | echo <text> | time | upload <file> | download <file> | close | exit")
    try:
        while True:
            try:
                line = input("udp> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            lowered = line.lower()
            if lowered in {"exit", "quit"}:
                break
            if lowered.startswith("upload "):
                client.upload(line[7:].strip())
                continue
            if lowered.startswith("download "):
                client.download(line[9:].strip())
                continue

            response = client.send_text(line)
            if response is None:
                print("[ERROR] No response (timeout / firewall DROP / server unavailable)")
                continue
            print(f"[SERVER] {response}")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="UDP client")
    parser.add_argument("host", nargs="?", default=HOST)
    parser.add_argument("port", nargs="?", type=int, default=PORT)
    args = parser.parse_args()
    interactive_client(args.host, args.port)


if __name__ == "__main__":
    main()