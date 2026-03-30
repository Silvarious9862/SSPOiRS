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


def upload_file(filename: str) -> None:
    # читаем весь локальный файл
    if not os.path.exists(filename):
        print(f"Local file not found: {filename}")
        return

    with open(filename, "rb") as f:
        data = f.read()

    total_size = len(data)
    print(f"Local file '{filename}', size={total_size} bytes")

    with socket.create_connection((HOST, PORT)) as sock:
        # 1) HELLO
        hello_raw = recv_line(sock)
        hello = strip_ansi(hello_raw)
        print(f"SERVER: {hello}")

        # 2) upload <filename> <size>
        cmd = f"upload {filename} {total_size}\n"
        sock.sendall(cmd.encode("utf-8"))

        # 3) ответ: OK READY или RESUME <offset> или ошибка
        status_raw = recv_line(sock)
        status = strip_ansi(status_raw)
        print(f"SERVER: {status}")

        if status.startswith("OK READY"):
            offset = 0
        elif status.startswith("RESUME "):
            try:
                offset = int(status.split()[1])
            except (IndexError, ValueError):
                print("Invalid RESUME offset from server")
                sock.sendall(b"exit\n")
                bye_raw = recv_line(sock)
                bye = strip_ansi(bye_raw)
                print(f"SERVER: {bye}")
                return
            if offset >= total_size:
                print(f"Nothing to upload, server already has {offset} bytes")
                # ждём финальный OK UPLOADED
                final_raw = recv_line(sock)
                final = strip_ansi(final_raw)
                print(f"SERVER: {final}")
                sock.sendall(b"exit\n")
                bye_raw = recv_line(sock)
                bye = strip_ansi(bye_raw)
                print(f"SERVER: {bye}")
                return
        else:
            print("Upload refused by server:", status)
            sock.sendall(b"exit\n")
            bye_raw = recv_line(sock)
            bye = strip_ansi(bye_raw)
            print(f"SERVER: {bye}")
            return

        # 4) отправляем оставшиеся байты (с учётом offset)
        remaining_data = data[offset:]
        if remaining_data:
            sock.sendall(remaining_data)
            print(f"Sent {len(remaining_data)} bytes from offset {offset}")
        else:
            print("No data to send (offset == total_size)")

        # 5) читаем финальный ответ: OK UPLOADED ... или ERROR ...
        final_raw = recv_line(sock)
        final = strip_ansi(final_raw)
        print(f"SERVER: {final}")

        # 6) корректно закрываем сессию
        sock.sendall(b"exit\n")
        bye_raw = recv_line(sock)
        bye = strip_ansi(bye_raw)
        print(f"SERVER: {bye}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Клиент для UPLOAD учебного сервера"
    )
    parser.add_argument("filename", help="Локальный файл для загрузки на сервер")
    args = parser.parse_args()
    upload_file(args.filename)


if __name__ == "__main__":
    main()