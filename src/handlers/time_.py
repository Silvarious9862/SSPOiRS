# src/handlers/time_.py
from __future__ import annotations

from datetime import datetime


def is_time_command(request: str) -> bool:
    """Проверка команды времени"""
    return request.strip().upper() == "TIME"


def get_current_time() -> str:
    """Получить текущее локальное время сервера"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def handle_time(request: str) -> str:
    """Обработка команды TIME"""
    if not is_time_command(request):
        return "ERROR: unknown command"
    return get_current_time()