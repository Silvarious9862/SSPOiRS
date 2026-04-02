"""udp_download_client.py — UDP client for DOWNLOAD with auto-resume."""
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

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

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


def parse_ok(message: str) -> tuple[int, int, int] | None:
    parts = message.split()
    if len(parts) != 4 or parts[0] != "OK":
        return None

    try:
        remaining = int(parts[1])
        chunk_size = int(parts[2])
        window_size = int(parts[3])
    except ValueError:
        return None

    return remaining, chunk_size, window_size


def parse_data_packet(data: bytes) -> tuple[int, bytes] | None:
    header, sep, payload = data.partition(b"\n")
    if not sep:
        return None

    try:
        header_text = strip_ansi(header.decode("utf-8").strip())
    except UnicodeDecodeError:
        return None

    parts = header_text.split()
    if len(parts) != 3 or parts[0] != "DATA":
        return None

    try:
        seq = int(parts[1])
        size = int(parts[2])
    except ValueError:
        return None

    if size < 0 or len(payload) != size:
        return None

    return seq, payload


def print_progress(received_now: int, total_now: int, offset: int, last_step: int) -> int:
    if total_now <= 0:
        return last_step

    percent = int(received_now * 100 / total_now)
    step = percent // 10

    if step > last_step:
        shown_percent = min(step * 10, 100)
        line = (
            f"{shown_percent:3d}% | Downloaded "
            f"{offset + received_now} / {offset + total_now} bytes"
        )
        sys.stdout.write("\r" + " " * 100 + "\r")
        sys.stdout.write(line)
        sys.stdout.flush()
        return step

    return last_step


def _download_once(
    host: str,
    port: int,
    remote_name: str,
    local_name: str,
    offset: int,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SOCKET_TIMEOUT)

    try:
        server_addr = (host, port)
        request = f"DOWNLOAD {remote_name} {offset}" if offset > 0 else f"DOWNLOAD {remote_name}"
        sock.sendto(request.encode("utf-8"), server_addr)

        message, addr = recv_text_datagram(sock)
        if addr != server_addr:
            raise RuntimeError(f"Unexpected server address: {addr}")

        print(f"SERVER: {message}")

        if message.startswith("ERROR"):
            raise RuntimeError(message)

        ok = parse_ok(message)
        if ok is None:
            raise RuntimeError(f"Unexpected response: {message}")

        remaining, _, _ = ok

        if remaining == 0:
            print("Nothing to download — local file is already complete.")
            return

        expected_seq = 0
        written = 0
        last_step = -1

        mode = "ab" if offset > 0 else "wb"
        with open(local_name, mode) as f:
            while True:
                data, addr = sock.recvfrom(RECV_BUFSIZE)
                if addr != server_addr:
                    continue

                try:
                    maybe_text = strip_ansi(data.decode("utf-8").strip())
                except UnicodeDecodeError:
                    maybe_text = None

                if maybe_text == "DONE":
                    sock.sendto(b"ACK DONE", server_addr)
                    break

                parsed = parse_data_packet(data)
                if parsed is None:
                    continue

                seq, payload = parsed

                if seq == expected_seq:
                    f.write(payload)
                    f.flush()
                    written += len(payload)
                    expected_seq += 1
                    last_step = print_progress(written, remaining, offset, last_step)

                ack_seq = expected_seq - 1
                sock.sendto(f"ACK {ack_seq}".encode("utf-8"), server_addr)

        last_step = print_progress(remaining, remaining, offset, last_step)
        print()

        try:
            final, addr = recv_text_datagram(sock)
            if addr == server_addr and final:
                print(f"SERVER: {final}")
        except socket.timeout:
            pass

    finally:
        sock.close()


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
        

def download_file(host: str, port: int, remote_name: str, local_name: str) -> None:
    attempt = 0

    while True:
        offset = 0
        if os.path.exists(local_name):
            offset = os.path.getsize(local_name)
            print(f"Local file '{local_name}' exists, offset={offset} bytes")
        else:
            print(f"Local file '{local_name}' does not exist, starting from 0")

        try:
            _download_once(host, port, remote_name, local_name, offset)
            return
        except (socket.timeout, TimeoutError, OSError) as exc:
            print(f"\n[CONNECTION] Transfer interrupted: {exc}")
            attempt, ok = _handle_failure(attempt)
            if not ok:
                return

def main() -> None:
    parser = argparse.ArgumentParser(description="UDP DOWNLOAD client")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("remote_name")
    parser.add_argument("local_name", nargs="?", default=None)
    args = parser.parse_args()

    local_name = args.local_name or args.remote_name
    download_file(args.host, args.port, args.remote_name, local_name)


if __name__ == "__main__":
    main()