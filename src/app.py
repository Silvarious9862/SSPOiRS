# src/app.py
from __future__ import annotations
import argparse
import sys
from src.settings import load_env, get_settings
from src.utils import logging as log

def parse_args():
    parser = argparse.ArgumentParser(
        description="Multi-protocol server (TCP/UDP) for labs"
    )
    parser.add_argument(
        "--proto",
        choices=["tcp", "udp"],
        help="Protocol: tcp or udp (default: tcp)",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "multiplex", "thread"],
        help="Server mode (default: single)",
    )
    parser.add_argument(
        "--host",
        help="Override bind host (for TCP/UDP)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override port (TCP for proto=tcp, UDP for proto=udp)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level",
    )

    # если нет аргументов - показать help и выйти
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        parser.exit(1)

    return parser.parse_args()

def main():
    load_env()
    base_settings = get_settings()
    args = parse_args()

    proto = args.proto or "tcp"
    mode = args.mode or "single"

    if proto == "tcp":
        host = args.host or base_settings.tcp_host
        port = args.port or base_settings.tcp_port
    else:
        host = args.host or base_settings.udp_host
        port = args.port or base_settings.udp_port

    # выбираем run_server
    if proto == "tcp" and mode == "single":
        from src.models.tcp_single import run_server
    elif proto == "udp" and mode == "single":
        from src.models.udp_single import run_server
    elif proto == "tcp" and mode == "multiplex":
        from src.models.tcp_select import run_server
    elif proto == "tcp" and mode == "thread":
        from src.models.tcp_thread import run_server
    else:
        log.error("Unsupported mode/proto combination")
        raise SystemExit("Unsupported mode/proto combination")

    effective_log_level = args.log_level or base_settings.log_level

    log.set_log_level(effective_log_level)
    log.info(f"Starting {proto.upper()} server in {mode} mode at {host}:{port}")

    run_server(host=host, port=port, log_level=effective_log_level)

if __name__ == "__main__":
    main()