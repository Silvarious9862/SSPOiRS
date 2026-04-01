# cython: language_level=3
from libc.stdint cimport int32_t
from cpython.bytes cimport PyBytes_AsStringAndSize

import socket  # обычный модуль, но тип сокета будем считать object
from src.utils import logging as log


cpdef bint send_window_core(
    object server_socket,
    tuple client_addr,
    list packets,
    int window_size,
    int max_retries,
):
    cdef int total_packets = len(packets)
    cdef int base = 0
    cdef int next_seq = 0
    cdef int retries = 0
    cdef int ack_seq
    cdef int seq

    from src.handlers_udp.download import wait_for_cumulative_ack  # импортируем Python-функцию

    while base < total_packets:
        while next_seq < total_packets and next_seq < base + window_size:
            try:
                server_socket.sendto(packets[next_seq], client_addr)
            except OSError as exc:
                log.debug(f"UDP send DATA failed: {exc}")
                return False
            next_seq += 1

        ack_seq = wait_for_cumulative_ack(server_socket, client_addr, base)

        if ack_seq == -1 or ack_seq is None:
            retries += 1
            if retries > max_retries:
                log.debug(
                    f"UDP download interrupted: ACK timeout window base={base}, "
                    f"client={client_addr[0]}:{client_addr[1]}"
                )
                return False

            log.debug(
                f"ACK timeout: retransmit window base={base}, next_seq={next_seq}, "
                f"retry={retries}/{max_retries}"
            )

            for seq in range(base, next_seq):
                try:
                    server_socket.sendto(packets[seq], client_addr)
                except OSError as exc:
                    log.debug(f"UDP resend DATA failed: {exc}")
                    return False
            continue

        if ack_seq >= total_packets:
            ack_seq = total_packets - 1

        if ack_seq < base:
            continue

        base = ack_seq + 1
        retries = 0

    return True