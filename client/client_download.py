from __future__ import annotations

import argparse
import os
import re
import socket

HOST = "127.0.0.1"
PORT = 5000

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def recv_line(sock: socket.socket) -> str:
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace").rstrip("\r\n")


def download_file(filename: str) -> None:
    offset = 0
    if os.path.exists(filename):
        offset = os.path.getsize(filename)
        print(f"Local file '{filename}' exists, offset={offset} bytes")
    else:
        print(f"Local file '{filename}' does not exist, starting from 0")

    with socket.create_connection((HOST, PORT)) as sock:
        hello_raw = recv_line(sock)
        hello = strip_ansi(hello_raw)
        print(f"SERVER: {hello}")

        if offset > 0:
            cmd = f"download {filename} {offset}\n"
        else:
            cmd = f"download {filename}\n"
        sock.sendall(cmd.encode("utf-8"))

        status_raw = recv_line(sock)
        status = strip_ansi(status_raw)
        print(f"SERVER: {status}")

        if not status.startswith("OK "):
            print("Download failed (no OK <size>)")
            sock.sendall(b"exit\n")
            bye_raw = recv_line(sock)
            bye = strip_ansi(bye_raw)
            print(f"SERVER: {bye}")
            return

        try:
            size = int(status.split()[1])
        except (IndexError, ValueError):
            print("Invalid size in server response")
            sock.sendall(b"exit\n")
            bye_raw = recv_line(sock)
            bye = strip_ansi(bye_raw)
            print(f"SERVER: {bye}")
            return

        if size == 0:
            print("Nothing to download (server reports 0 bytes remaining)")
        else:
            remaining = size
            received = 0
            mode = "ab" if offset > 0 else "wb"

            with open(filename, mode) as f:
                while remaining > 0:
                    chunk = sock.recv(min(65536, remaining))
                    if not chunk:
                        print("Connection closed during download")
                        break

                    f.write(chunk)
                    f.flush()
                    received += len(chunk)
                    remaining -= len(chunk)

            print(f"Downloaded now: {received} bytes")
            if received != size:
                print(f"Warning: expected {size} bytes, got {received}")
                print(f"Partial file saved locally, current size={os.path.getsize(filename)} bytes")

        final_raw = recv_line(sock)
        final = strip_ansi(final_raw)
        if final:
            print(f"SERVER: {final}")

        sock.sendall(b"exit\n")
        bye_raw = recv_line(sock)
        bye = strip_ansi(bye_raw)
        print(f"SERVER: {bye}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Клиент для DOWNLOAD"
    )
    parser.add_argument("filename", help="Имя файла на сервере/локально")
    args = parser.parse_args()
    download_file(args.filename)


if __name__ == "__main__":
    main()