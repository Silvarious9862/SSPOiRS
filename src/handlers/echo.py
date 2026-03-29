# src/handlers/echo.py
from __future__ import annotations


def is_echo_command(request: str) -> bool:
    return request.upper().startswith("ECHO")


def extract_echo_message(request: str) -> str:
    return request[4:].strip()


def handle_echo(request: str) -> str:
    if not is_echo_command(request):
        return "ERROR: unknown command"
    message = extract_echo_message(request)
    return message or "ERROR: empty echo message"
