# src/models/tcp_thread.py
from __future__ import annotations

import threading
from typing import NoReturn

from src.utils import logging as log
from src.tcp_protocol import create_listen_socket, accept_client, handle_client
from src.utils.runtime import shutdown_event, clients_lock, active_clients


def _register_client(client_addr, client_socket, thread: threading.Thread) -> None:
    with clients_lock:
        active_clients[client_addr] = {
            "socket": client_socket,
            "thread": thread,
            "state": "idle",
        }


def _unregister_client(client_addr) -> None:
    with clients_lock:
        active_clients.pop(client_addr, None)


def set_client_state(client_addr, state: str) -> None:
    with clients_lock:
        info = active_clients.get(client_addr)
        if info is not None:
            info["state"] = state


def _snapshot_clients() -> list[tuple[str, int, str, str]]:
    """
    Возвращает список (addr, thread_name, state) для монитора.
    """
    with clients_lock:
        result: list[tuple[str, int, str, str]] = []
        for (host, port), info in active_clients.items():
            thread = info.get("thread")
            state = info.get("state", "idle")
            tname = thread.name if isinstance(thread, threading.Thread) else "?"
            result.append((host, port, tname, state))
        return result


def _close_all_clients() -> None:
    """
    Принудительно закрыть все клиентские сокеты.
    После этого все worker-потоки вывалятся из recv() и завершатся.
    """
    with clients_lock:
        items = [
            ((host, port), info.get("socket"), info.get("thread"))
            for (host, port), info in active_clients.items()
        ]

    for (host, port), sock, thread in items:
        if sock is None:
            continue
        try:
            tname = thread.name if isinstance(thread, threading.Thread) else "?"
            log.debug(
                f"[shutdown] Closing client socket {host}:{port} "
                f"in thread {tname}"
            )
            sock.close()
        except OSError as exc:
            log.debug(
                f"[shutdown] Error while closing socket {host}:{port}: {exc}"
            )


def _clients_monitor(interval: float = 60.0) -> None:
    """
    Фоновый монитор: раз в interval секунд пишет таблицу активных клиентов.
    Останавливается, когда выставлен shutdown_event.
    """
    thread_name = threading.current_thread().name
    log.debug(f"[{thread_name}] Clients monitor started, interval={interval}s")

    main_state = "listen"

    while not shutdown_event.wait(interval):
        rows = _snapshot_clients()

        # Заголовок таблицы
        lines = []
        lines.append("[monitor] Connections state")
        lines.append(
            f"{'thread':<32} | {'addr':<21} | state"
        )
        lines.append("-" * 32 + "-+-" + "-" * 21 + "-+-" + "-" * 10)

        # MainThread (listen на accept)
        lines.append(
            f"{'MainThread':<32} | {'*:' + str(server_port):<21} | {main_state}"
        )

        # Клиенты
        if not rows:
            lines.append("(no active clients)")
        else:
            for host, port, tname, state in rows:
                addr = f"{host}:{port}"
                lines.append(
                    f"{tname:<32} | {addr:<21} | {state}"
                )

        log.debug("\n".join(lines))

    log.debug(f"[{thread_name}] Clients monitor stopped")


def _client_worker(client_socket, client_addr) -> None:
    """
    Поток обслуживания одного TCP-клиента.
    Вся логика протокола уже находится в handle_client().
    """
    thread = threading.current_thread()
    thread_name = thread.name

    _register_client(client_addr, client_socket, thread)
    set_client_state(client_addr, "idle")

    log.debug(
        f"[{thread_name}] Started worker for "
        f"{client_addr[0]}:{client_addr[1]}"
    )

    try:
        handle_client(client_socket, client_addr)
    finally:
        _unregister_client(client_addr)
        log.debug(
            f"[{thread_name}] Finished worker for "
            f"{client_addr[0]}:{client_addr[1]}"
        )


def serve_forever(server_socket) -> None:
    while not shutdown_event.is_set():
        accepted = accept_client(server_socket)
        if accepted is None:
            # timeout accept() — проверим флаг и дальше
            continue

        client_socket, client_addr = accepted

        worker = threading.Thread(
            target=_client_worker,
            args=(client_socket, client_addr),
            daemon=False,
            name=f"tcp-client-{client_addr[0]}:{client_addr[1]}",
        )
        worker.start()

        log.debug(
            f"Spawned thread {worker.name} for "
            f"{client_addr[0]}:{client_addr[1]}"
        )


def shutdown_server(server_socket) -> None:
    try:
        server_socket.close()
    finally:
        log.info("TCP threaded server stopped")


# server_port нужен монитору, зададим его в run_server
server_port = 0


def run_server(host: str, port: int, log_level: str = "INFO") -> NoReturn:
    """
    ЛР4: многопоточный TCP-сервер.
    Для каждого принятого соединения порождается отдельный поток.
    """
    global server_port
    server_port = port

    log.set_log_level(log_level)
    log.debug(f"Current log level: {log_level}")

    server_socket = create_listen_socket(host, port)
    log.info(f"TCP threaded server started on {host}:{port}")

    monitor = threading.Thread(
        target=_clients_monitor,
        args=(15.0,),
        daemon=True,
        name="tcp-clients-monitor",
    )
    monitor.start()

    try:
        serve_forever(server_socket)
    except KeyboardInterrupt:
        log.warn("Shutdown requested by Ctrl+C")
        shutdown_event.set()
        shutdown_server(server_socket)
        _close_all_clients()
    finally:
        pass

    raise SystemExit(0)