"""client_upload.py — клиент загрузки файлов на сервер с SO_KEEPALIVE и автовосстановлением."""
from __future__ import annotations

import argparse
import os
import re
import socket
import struct
import time

HOST = "127.0.0.1"
PORT = 5000

KEEPALIVE_IDLE = 15
KEEPALIVE_INTVL = 5
KEEPALIVE_CNT = 4

RETRY_DELAYS = [0.5, 1, 2, 5, 10, 30]
RECV_TIMEOUT = 60.0

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def _apply_keepalive(sock: socket.socket) -> None:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, KEEPALIVE_IDLE)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, KEEPALIVE_INTVL)
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, KEEPALIVE_CNT)
    if hasattr(socket, "SIO_KEEPALIVE_VALS"):
        sock.ioctl(
            socket.SIO_KEEPALIVE_VALS,
            (1, KEEPALIVE_IDLE * 1000, KEEPALIVE_INTVL * 1000),
        )


def recv_line(sock: socket.socket) -> str:
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace").rstrip()


def _connect_and_handshake() -> socket.socket:
    sock = socket.create_connection((HOST, PORT))
    _apply_keepalive(sock)
    sock.settimeout(RECV_TIMEOUT)
    hello = strip_ansi(recv_line(sock))
    print(f"SERVER: {hello}")
    return sock


def _handle_failure(attempt: int) -> tuple[int, bool]:
    """
    Лестница задержек:
    0.5s, 1s, 2s, 5s, 10s, 30s.
    После этого решение остаётся за пользователем.
    """
    attempt += 1

    if attempt <= len(RETRY_DELAYS):
        delay = RETRY_DELAYS[attempt - 1]
        print(
            f"[RECONNECT] Auto-retry {attempt}/{len(RETRY_DELAYS)} "
            f"in {delay:.1f}s…"
        )
        time.sleep(delay)
        return attempt, True

    print(
        f"\n[CONNECTION PROBLEM] Failed after {len(RETRY_DELAYS)} automatic "
        "retries. The connection to the server cannot be established."
    )
    while True:
        answer = input("Retry connection? [y/n]: ").strip().lower()
        if answer == "y":
            delay = RETRY_DELAYS[-1]
            print(f"[RECONNECT] Retrying in {delay:.0f}s…")
            time.sleep(delay)
            return attempt, True
        if answer == "n":
            print("Transfer aborted by user.")
            return attempt, False

def upload_file(filename: str) -> None:
    if not os.path.exists(filename):
        print(f"Local file not found: {filename}")
        return

    with open(filename, "rb") as f:
        data = f.read()
    total_size = len(data)
    print(f"Local file: {filename}, size={total_size} bytes")

    attempt = 0

    while True:
        try:
            sock = _connect_and_handshake()
        except (OSError, ConnectionRefusedError) as exc:
            print(f"[CONNECTION] Cannot connect to {HOST}:{PORT}: {exc}")
            attempt, ok = _handle_failure(attempt)
            if not ok:
                return
            continue

        try:
            sock.sendall(f"upload {filename} {total_size}".encode("utf-8"))

            raw_status = recv_line(sock)
            print(f"SERVER RAW: {raw_status!r}")  # то, что пришло по сети

            status = strip_ansi(raw_status)
            print(f"SERVER STRIPPED: {status!r}")  # после удаления ANSI

            offset = 0

            if status.startswith("OK READY"):
                offset = 0

            elif status.startswith("RESUME"):
                try:
                    offset_str = status.split()[1]
                    offset = int(offset_str)
                except (IndexError, ValueError) as exc:
                    print("Invalid RESUME offset from server.")
                    try:
                        sock.sendall(b"exit")
                    except OSError:
                        pass
                    return

            else:
                print(f"Upload refused by server: {status}")
                try:
                    sock.sendall(b"exit")
                except OSError:
                    pass
                return

            remaining_data = data[offset:]
            interrupted = False

            try:
                sent = 0
                chunk_size = 4096
                while sent < len(remaining_data):
                    piece = remaining_data[sent:sent + chunk_size]
                    sock.sendall(piece)
                    sent += len(piece)
                    print(
                        f"\rUploaded {offset + sent} / {total_size} bytes",
                        end="", flush=True,
                    )
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                print(f"\n[CONNECTION] Transfer interrupted: {exc}")
                interrupted = True

            print()

            if interrupted:
                attempt, ok = _handle_failure(attempt)
                try:
                    sock.close()
                except OSError:
                    pass
                if ok:
                    continue
                return

            final = strip_ansi(recv_line(sock))
            if final:
                print(f"SERVER: {final}")
            sock.sendall(b"exit")
            recv_line(sock)
            attempt = 0
            return

        except (OSError, ConnectionResetError, BrokenPipeError) as exc:
            print(f"\n[CONNECTION] Unexpected error: {exc}")
            attempt, ok = _handle_failure(attempt)
            if not ok:
                return
        finally:
            try:
                sock.close()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="UPLOAD")
    parser.add_argument("filename", help="File to upload")
    args = parser.parse_args()
    upload_file(args.filename)


if __name__ == "__main__":
    main()