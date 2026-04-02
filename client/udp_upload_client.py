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
CHUNK_SIZE: Final[int] = 1450
WINDOW_SIZE: Final[int] = 32
ACK_TIMEOUT: Final[float] = 0.1
MAX_RETRIES: Final[int] = 20

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


def build_data_packet(seq: int, chunk: bytes) -> bytes:
    header = f"DATA {seq} {len(chunk)}\n".encode("utf-8")
    return header + chunk


def _upload_once(
    host: str,
    port: int,
    local_name: str,
    remote_name: str,
) -> None:
    if not os.path.exists(local_name):
        raise RuntimeError(f"Local file '{local_name}' does not exist")

    total_size = os.path.getsize(local_name)
    if total_size <= 0:
        raise RuntimeError("Cannot upload empty file (size 0)")

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
                raise RuntimeError("Invalid RESUME offset from server.")
        elif status.startswith("OK READY"):
            offset = 0
        elif status.startswith("OK UPLOADED"):
            print(f"SERVER: {status}")
            return
        elif status.startswith("ERROR"):
            raise RuntimeError(status)
        else:
            raise RuntimeError(f"Upload refused by server: {status}")

        remaining = total_size - offset
        if remaining == 0:
            print("Nothing to upload — server already has full file.")
            try:
                final, addr = recv_text_datagram(sock)
                if addr == server_addr and final:
                    print(f"SERVER: {final}")
            except socket.timeout:
                pass
            return

        # читаем файл в память так же, как сервер download
        packets: list[bytes] = []
        with open(local_name, "rb") as f:
            if offset > 0:
                f.seek(offset)
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                packets.append(build_data_packet(len(packets), chunk))

        total_packets = len(packets)
        base = 0
        next_seq = 0
        retries = 0
        sent_bytes = 0
        last_step = -1

        print(f"Starting UDP upload, packets={total_packets}, window={WINDOW_SIZE}")

        start = time.perf_counter()

        while base < total_packets:
            # досылаем окно
            while next_seq < total_packets and next_seq < base + WINDOW_SIZE:
                try:
                    sock.sendto(packets[next_seq], server_addr)
                except OSError as exc:
                    raise OSError(f"UDP send DATA failed: {exc}") from exc
                next_seq += 1

            # ждём cumulative ACK
            ack_seq = _wait_for_cumulative_ack_client(sock, server_addr, base)

            if ack_seq is None:
                retries += 1
                if retries > MAX_RETRIES:
                    raise TimeoutError(
                        f"UDP upload interrupted: ACK timeout window base={base}"
                    )

                for seq in range(base, next_seq):
                    try:
                        sock.sendto(packets[seq], server_addr)
                    except OSError as exc:
                        raise OSError(f"UDP resend DATA failed: {exc}") from exc
                continue

            if ack_seq >= total_packets:
                ack_seq = total_packets - 1
            if ack_seq < base:
                continue

            # обновляем base и прогресс
            newly_acked = ack_seq - base + 1
            base = ack_seq + 1
            retries = 0

            sent_bytes = min(total_size - offset, base * CHUNK_SIZE)
            last_step = print_progress(offset + sent_bytes, total_size, last_step)

        duration = time.perf_counter() - start
        print_progress(offset + remaining, total_size, last_step)
        print()

        msg, addr = recv_text_datagram(sock)
        if addr == server_addr and msg:
            print(f"SERVER: {msg}")
    finally:
        sock.close()

def _wait_for_cumulative_ack_client(
    sock: socket.socket,
    server_addr: tuple[str, int],
    min_expected: int,
) -> int | None:
    old_timeout = sock.gettimeout()
    sock.settimeout(ACK_TIMEOUT)
    try:
        while True:
            try:
                data, addr = sock.recvfrom(RECV_BUFSIZE)
            except (socket.timeout, TimeoutError):
                return None
            except OSError:
                return None

            if addr != server_addr:
                continue

            try:
                text = data.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue

            parts = text.split()
            if len(parts) != 2 or parts[0] != "ACK":
                continue

            try:
                ack_seq = int(parts[1])
            except ValueError:
                continue

            if ack_seq >= min_expected:
                return ack_seq
    finally:
        sock.settimeout(old_timeout)

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