# src/handlers/close.py
from __future__ import annotations

CLOSE_COMMANDS = {"CLOSE", "EXIT", "QUIT"}

def is_close_command(request: str) -> bool:
    return request.upper() in CLOSE_COMMANDS
