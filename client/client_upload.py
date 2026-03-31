"""client_upload.py — клиент выгрузки файла на сервер с SO_KEEPALIVE, OOB-прогрессом и автовосстановлением."""
from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import time

HOST = "127.0.0.1"
PORT = 5000

KEEPALIVE_IDLE = 15
KEEPALIVE_INTVL = 5
KEEPALIVE_CNT = 4

RETRY_DELAYS = [0.5, 1, 2, 5, 10, 30]
SEND_TIMEOUT = 60.0
OOB_PROGRESS_STEP = 10

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
    sock.settimeout(SEND_TIMEOUT)
    hello = strip_ansi(recv_line(sock))
    print(f"SERVER: {hello}")
    return sock


def _handle_failure(attempt: int) -> tuple[int, bool]:
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
        
def send_oob_progress(sock: socket.socket, percent: int) -> None:
    try:
        sock.send(bytes([percent]), socket.MSG_OOB)
    except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
        pass

def upload_file(filepath: str) -> None:
    if not os.path.exists(filepath):
        print(f"Local file not found: {filepath}")
        return

    if not os.path.isfile(filepath):
        print(f"Path is not a regular file: {filepath}")
        return

    filename = os.path.basename(filepath)
    total_size = os.path.getsize(filepath)
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
            cmd = f"upload {filename} {total_size}"
            sock.sendall(cmd.encode("utf-8"))

            raw_status = recv_line(sock)
            print(f"SERVER RAW: {raw_status!r}")

            status = strip_ansi(raw_status)
            print(f"SERVER STRIPPED: {status!r}")

            offset = 0
            if status.startswith("RESUME "):
                try:
                    offset = int(status.split()[1])
                except (IndexError, ValueError):
                    print("Invalid RESUME offset from server.")
                    return
            elif status.startswith("OK READY"):
                offset = 0
            elif status.startswith("OK UPLOADED"):
                print(f"SERVER: {status}")
                return
            else:
                print("Upload refused by server.")
                try:
                    sock.sendall(b"exit")
                    recv_line(sock)
                except OSError:
                    pass
                return

            if offset > total_size:
                print(
                    f"Server requested invalid resume offset {offset}, "
                    f"local file size is {total_size}."
                )
                return

            remaining = total_size - offset
            if remaining == 0:
                print("Nothing to upload — server already has the whole file.")
                final = strip_ansi(recv_line(sock))
                if final:
                    print(f"SERVER: {final}")
                try:
                    sock.sendall(b"exit")
                    recv_line(sock)
                except OSError:
                    pass
                return

            sent = 0
            interrupted = False
            status_line = ""
            progress_oob = None

            sent = 0
            interrupted = False
            status_line = ""
            progress_oob = None
            last_oob_step = -1

            with open(filepath, "rb") as f:
                f.seek(offset)

                while sent < remaining:
                    chunk = f.read(min(65536, remaining - sent))
                    if not chunk:
                        break

                    try:
                        sock.sendall(chunk)
                    except (socket.timeout, TimeoutError):
                        print(
                            f"\n[CONNECTION] Send timeout after {SEND_TIMEOUT:.0f}s — "
                            "connection appears lost."
                        )
                        interrupted = True
                        break
                    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                        print(f"\n[CONNECTION] Transfer interrupted: {exc}")
                        interrupted = True
                        break

                    sent += len(chunk)

                    # считаем свой прогресс и шлём OOB на сервер (отправитель файла = клиент)
                    percent = int(sent * 100 / remaining)
                    step = percent // OOB_PROGRESS_STEP
                    if step > last_oob_step and percent < 100:
                        oob_percent = min(step * OOB_PROGRESS_STEP, 99)
                        send_oob_progress(sock, oob_percent)
                        progress_oob = oob_percent
                        last_oob_step = step

                    # формируем единую строку статуса
                    parts = []
                    if progress_oob is not None:
                        parts.append(f"{progress_oob:3d}%")
                    parts.append(f"Uploaded {offset + sent} / {total_size} bytes")
                    new_status = " | ".join(parts)

                    # перерисовываем только если что-то поменялось
                    if new_status != status_line:
                        status_line = new_status
                        sys.stdout.write("\r" + " " * 80 + "\r")
                        sys.stdout.write(status_line)
                        sys.stdout.flush()

            # гарантированно показать финальные 100%
            if not interrupted and sent == remaining:
                send_oob_progress(sock, 100)
                progress_oob = 100
                status_line = f"{progress_oob:3d}% | Uploaded {offset + sent} / {total_size} bytes"
            else:
                status_line = f"Uploaded {offset + sent} / {total_size} bytes"

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

            if offset + sent != total_size:
                print(
                    f"\nWarning: expected to upload {remaining} bytes, sent only {sent}."
                )

            final = strip_ansi(recv_line(sock))
            if final:
                print(f"SERVER: {final}")

            try:
                sock.sendall(b"exit")
                recv_line(sock)
            except OSError:
                pass

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
    parser.add_argument("filepath", help="Local file to upload")
    args = parser.parse_args()
    upload_file(args.filepath)


if __name__ == "__main__":
    main()