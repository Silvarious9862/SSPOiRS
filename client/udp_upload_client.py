"""udp_upload_client.py — UDP client for UPLOAD with auto-resume."""
from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import time
from typing import Final

RECV_BUFSIZE: Final[int] = 65535
SOCKET_TIMEOUT: Final[float] = 5.0

ANSI_ESCAPE_RE = re.compile(r"\x1B\\[[0-?]*[ -/]*[@-~]")

RETRY_DELAYS = [0.5, 1, 2, 5, 10, 30]


def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def recv_text_datagram(sock: socket.socket) -> tuple[str, tuple[str, int]]:
    while True:
        data, addr = sock.recvfrom(RECV_BUFSIZE)
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        return strip_ansi(text), addr


def print_progress(sent_now: int, total_now: int, last_step: int) -> int:
    if total_now <= 0:
        return last_step

    percent = int(sent_now * 100 / total_now)
    step = percent // 10

    if step > last_step:
        shown_percent = min(step * 10, 100)
        line = f"{shown_percent:3d}% | Uploaded {sent_now} / {total_now} bytes"
        sys.stdout.write("\r" + " " * 100 + "\r")
        sys.stdout.write(line)
        sys.stdout.flush()
        return step

    return last_step


def _upload_once(
    host: str,
    port: int,
    local_name: str,
    remote_name: str,
) -> None:
    if not os.path.exists(local_name):
        raise RuntimeError(f"Local file '{local_name}' does not exist")

    total_size = os.path.getsize(local_name)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SOCKET_TIMEOUT)

    try:
        server_addr = (host, port)
        cmd = f"UPLOAD {remote_name} {total_size}"
        sock.sendto(cmd.encode("utf-8"), server_addr)

        status, addr = recv_text_datagram(sock)
        if addr != server_addr:
            raise RuntimeError(f"Unexpected server address: {addr}")

        print(f"SERVER: {status}")

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
            return

        # подтверждаем выбор offset
        if offset > 0:
            ack_msg = f"RESUME {offset}"
        else:
            ack_msg = "OK READY"
        sock.sendto(ack_msg.encode("utf-8"), server_addr)

        remaining = total_size - offset
        if remaining == 0:
            print("Nothing to upload — server already has full file.")
            return

        sent = 0
        last_step = -1

        with open(local_name, "rb") as f:
            if offset > 0:
                f.seek(offset)

            while sent < remaining:
                chunk = f.read(min(65536, remaining - sent))
                if not chunk:
                    break

                sock.sendto(chunk, server_addr)
                sent += len(chunk)
                last_step = print_progress(sent, total_size, last_step)

        # сигнал окончания
        sock.sendto(b"DONE", server_addr)

        # ждём ACK DONE и финальный статус
        try:
            status, addr = recv_text_datagram(sock)
            if addr == server_addr and status == "ACK DONE":
                status, addr = recv_text_datagram(sock)
                if addr == server_addr and status:
                    print(f"\nSERVER: {status}")
            else:
                print("\nSERVER:", status)
        except socket.timeout:
            print("\n[WARNING] No final ACK DONE from server.")
    finally:
        sock.close()


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


def upload_file(host: str, port: int, local_name: str, remote_name: str) -> None:
    attempt = 0

    while True:
        try:
            _upload_once(host, port, local_name, remote_name)
            return
        except (socket.timeout, TimeoutError, OSError) as exc:
            print(f"\n[CONNECTION] Transfer interrupted: {exc}")
            attempt, ok = _handle_failure(attempt)
            if not ok:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="UDP UPLOAD client")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("local_name")
    parser.add_argument("remote_name", nargs="?", default=None)
    args = parser.parse_args()

    remote_name = args.remote_name or os.path.basename(args.local_name)
    upload_file(args.host, args.port, args.local_name, remote_name)


if __name__ == "__main__":
    main()