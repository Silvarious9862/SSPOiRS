# src/utils/files.py
from __future__ import annotations

import threading
from pathlib import Path

from src.settings import get_settings

_files_lock = threading.Lock()
_uploads_in_progress: set[str] = set()


def get_base_dir() -> Path:
    settings = get_settings()
    base = settings.files_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_filename(filename: str) -> str:
    """
    Нормализуем имя файла и не даём выйти за пределы корневой папки.
    """
    return Path(filename).name


def get_file_path(filename: str) -> Path:
    """
    Безопасное получение пути: запрещаем выход выше корня (..).
    """
    base = get_base_dir()
    name = normalize_filename(filename)
    return base / name


def save_bytes(filename: str, data: bytes) -> Path:
    """
    Сохранить байты в файл (перезаписывает, если есть).
    """
    path = get_file_path(filename)
    path.write_bytes(data)
    return path


def load_bytes(filename: str) -> tuple[bytes, int]:
    """
    Прочитать файл в память. Возвращает (data, size).
    """
    path = get_file_path(filename)
    data = path.read_bytes()
    return data, len(data)


def try_acquire_upload(filename: str) -> bool:
    """
    Пытается пометить файл как занятый под upload.
    Возвращает False, если кто-то уже загружает этот файл.
    """
    name = normalize_filename(filename)

    with _files_lock:
        if name in _uploads_in_progress:
            return False

        _uploads_in_progress.add(name)
        return True


def release_upload(filename: str) -> None:
    """
    Снять блокировку upload для файла.
    Безопасно даже если файл уже отсутствует в наборе.
    """
    name = normalize_filename(filename)

    with _files_lock:
        _uploads_in_progress.discard(name)


def is_upload_in_progress(filename: str) -> bool:
    """
    Проверить, занят ли файл активной загрузкой.
    """
    name = normalize_filename(filename)

    with _files_lock:
        return name in _uploads_in_progress