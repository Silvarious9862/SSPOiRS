# src/utils/files.py
from __future__ import annotations

from pathlib import Path
from typing import Tuple

from settings import get_settings


def get_base_dir() -> Path:
    settings = get_settings()
    base = settings.files_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_file_path(filename: str) -> Path:
    """
    Безопасное получение пути: запрещаем выход выше корня (..).
    """
    base = get_base_dir()
    # убираем возможные разделители каталогов
    name = Path(filename).name
    return base / name


def save_bytes(filename: str, data: bytes) -> Path:
    """
    Сохранить байты в файл (перезаписывает, если есть).
    """
    path = get_file_path(filename)
    path.write_bytes(data)
    return path


def load_bytes(filename: str) -> Tuple[bytes, int]:
    """
    Прочитать файл в память. Возвращает (data, size).
    """
    path = get_file_path(filename)
    data = path.read_bytes()
    return data, len(data)
