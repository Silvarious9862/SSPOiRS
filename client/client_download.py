"""client_download.py — клиент загрузки с SO_KEEPALIVE и автовосстановлением."""
from __future__ import annotations

import argparse
import os
import re
import socket
import time
import select
import sys

HOST = "127.0.0.1"
PORT = 5000

KEEPALIVE_IDLE = 15
KEEPALIVE_INTVL = 5
KEEPALIVE_CNT = 4

RETRY_DELAYS = [0.5, 1, 2, 5, 10, 30]    # базовая задержка перед повтором (с)
RECV_TIMEOUT = 60.0       # таймаут отсутствия данных → разрыв (с)

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

def _poll_oob_progress(sock: socket.socket) -> None:
    """
    Ненавязчиво проверяет, пришли ли внеполосные данные с прогрессом,
    и печатает их, не блокируя основной приём файла.
    """
    try:
        r, _, x = select.select([], [], [sock], 0)
    except OSError:
        return

    if sock in x:
        try:
            data = sock.recv(1, socket.MSG_OOB)
        except OSError:
            return
        if data:
            percent = data[0]
            print(f"\n[OOB] progress: {percent}%", flush=True)

def download_file(filename: str) -> None:
    attempt = 0

    while True:
        offset = 0
        if os.path.exists(filename):
            offset = os.path.getsize(filename)
            print(f"Local file '{filename}' exists, offset={offset} bytes")
        else:
            print(f"Local file '{filename}' does not exist, starting from 0")

        try:
            sock = _connect_and_handshake()
        except (OSError, ConnectionRefusedError) as exc:
            print(f"[CONNECTION] Cannot connect to {HOST}:{PORT}: {exc}")
            attempt, ok = _handle_failure(attempt)
            if not ok:
                return
            continue

        try:
            cmd = (f"download {filename} {offset}"
                   if offset > 0 else f"download {filename}")
            sock.sendall(cmd.encode("utf-8"))

            raw_status = recv_line(sock)
            print(f"SERVER RAW: {raw_status!r}")

            status = strip_ansi(raw_status)
            print(f"SERVER STRIPPED: {status!r}")

            # Если сервер сказал, что файла нет, а мы хотели резюмировать
            if status.startswith("ERROR file not found") and offset > 0:
                print(
                    "Server does not have this file (or has shorter version) — "
                    "resume from local offset is impossible."
                )
                try:
                    sock.sendall(b"exit")
                    recv_line(sock)
                except OSError:
                    pass
                return

            if not status.startswith("OK"):
                print("Download refused by server.")
                try:
                    sock.sendall(b"exit")
                    recv_line(sock)
                except OSError:
                    pass
                return

            try:
                size = int(status.split()[1])
            except (IndexError, ValueError):
                print("Invalid size in server response.")
                try:
                    sock.sendall(b"exit")
                    recv_line(sock)
                except OSError:
                    pass
                return

            progress_percent = -1

            if size == 0:
                print("Nothing to download — server reports 0 bytes remaining.")
                final = strip_ansi(recv_line(sock))
                if final:
                    print(f"SERVER: {final}")
                try:
                    sock.sendall(b"exit")
                    recv_line(sock)
                except OSError:
                    pass
                return

            remaining = size
            received = 0
            mode = "ab" if offset > 0 else "wb"
            interrupted = False

            status_line = ""
            progress_oob = None

            with open(filename, mode) as f:
                while remaining > 0:
                    # сначала проверяем OOB
                    r, _, x = select.select([sock], [], [sock], 0)
                    if sock in x:
                        try:
                            oob = sock.recv(1, socket.MSG_OOB)
                            if oob:
                                progress_oob = oob[0]
                        except OSError:
                            pass

                    # читаем обычные данные
                    try:
                        chunk = sock.recv(min(65536, remaining))
                    except (socket.timeout, TimeoutError):
                        print(
                            f"\n[CONNECTION] No data for {RECV_TIMEOUT:.0f}s — "
                            "connection appears lost."
                        )
                        interrupted = True
                        break
                    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                        print(f"\n[CONNECTION] Transfer interrupted: {exc}")
                        interrupted = True
                        break

                    if not chunk:
                        if remaining > 0:
                            print("\n[CONNECTION] Connection closed by server during transfer.")
                            interrupted = True
                        break

                    f.write(chunk)
                    f.flush()
                    received += len(chunk)
                    remaining -= len(chunk)

                    # формируем единую строку статуса
                    parts = []
                    if progress_oob is not None:
                        parts.append(f"{progress_oob:3d}%")
                    parts.append(f"Downloaded {offset + received} / {offset + size} bytes")
                    new_status = " | ".join(parts)

                    # перерисовываем только если что-то поменялось
                    if new_status != status_line:
                        status_line = new_status
                        sys.stdout.write("\r" + " " * 80 + "\r")  # очистить строку
                        sys.stdout.write(status_line)
                        sys.stdout.flush()

            # гарантированно показать финальные 100%
            progress_oob = 100
            status_line = f"{progress_oob:3d}% | Downloaded {offset + received} / {offset + size} bytes"
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.write(status_line)
            sys.stdout.flush()
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

            if received != size:
                print(f"\nWarning: expected {size} bytes, got {received}.")

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
    parser = argparse.ArgumentParser(description="DOWNLOAD")
    parser.add_argument("filename", help="File to download")
    args = parser.parse_args()
    download_file(args.filename)


if __name__ == "__main__":
    main()