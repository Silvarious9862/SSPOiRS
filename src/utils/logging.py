# src/utils/logging.py
from __future__ import annotations

import sys
from datetime import datetime
from typing import Literal

from src.utils.colors import colorize

LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR"]

_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40,
}

_current_level: LogLevel = "INFO"


def set_log_level(level: str) -> None:
    level = level.upper()
    if level not in _LEVEL_ORDER:
        raise ValueError(f"Unknown log level: {level}")
    global _current_level
    _current_level = level


def _should_log(level: LogLevel) -> bool:
    return _LEVEL_ORDER[level] >= _LEVEL_ORDER[_current_level]


def _log(level: LogLevel, msg: str) -> None:
    if not _should_log(level):
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}] [{level}] "
    line = prefix + msg
    # маппинг уровней к цветам из colors.py
    color_level = {
        "DEBUG": "debug",
        "INFO": "info",
        "WARN": "warn",
        "ERROR": "error",
    }[level]
    colored = colorize(line, level=color_level)
    print(colored, file=sys.stderr)


def debug(msg: str) -> None:
    _log("DEBUG", msg)


def info(msg: str) -> None:
    _log("INFO", msg)


def warn(msg: str) -> None:
    _log("WARN", msg)


def error(msg: str) -> None:
    _log("ERROR", msg)
