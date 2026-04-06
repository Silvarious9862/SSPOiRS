# src/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass
class Settings:
    # Общие
    env: str
    log_level: str
    files_dir: Path

    # TCP
    tcp_host: str
    tcp_port: int

    # UDP
    udp_host: str
    udp_port: int

    # Thread-pool (ЛР4)
    thread_nmin: int
    thread_nmax: int
    thread_idle_timeout: float  # секунды


_settings: Settings | None = None


def load_env(override: bool = False) -> None:
    """
    Загружает .env в os.environ.
    Вызывать один раз при старте приложения.
    """
    load_dotenv(dotenv_path=ENV_PATH, override=override)


def _get_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"Required env var {name} is not set")
    return value


def get_settings() -> Settings:
    """
    Ленивая инициализация настроек.
    settings = get_settings() можно вызывать где угодно.
    """
    global _settings
    if _settings is not None:
        return _settings

    # общие
    env = os.getenv("APP_ENV", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    files_dir = Path(os.getenv("FILES_DIR", PROJECT_ROOT / "serverfiles")).resolve()

    # tcp
    tcp_host = os.getenv("TCP_HOST", "0.0.0.0")
    tcp_port = int(os.getenv("TCP_PORT", "5000"))

    # udp
    udp_host = os.getenv("UDP_HOST", "0.0.0.0")
    udp_port = int(os.getenv("UDP_PORT", "5001"))

    # thread pool
    thread_nmin = int(os.getenv("THREAD_NMIN", "2"))
    thread_nmax = int(os.getenv("THREAD_NMAX", "16"))
    thread_idle_timeout = float(os.getenv("THREAD_IDLE_TIMEOUT", "30"))

    _settings = Settings(
        env=env,
        log_level=log_level,
        files_dir=files_dir,
        tcp_host=tcp_host,
        tcp_port=tcp_port,
        udp_host=udp_host,
        udp_port=udp_port,
        thread_nmin=thread_nmin,
        thread_nmax=thread_nmax,
        thread_idle_timeout=thread_idle_timeout,
    )
    return _settings
