# src/colors.py
RESET = "\x1b[0m"
COLORS = {
    "info":  "\x1b[32m",  # зелёный
    "debug": "\x1b[36m",  # циан
    "error": "\x1b[31m",  # красный
    "warn":  "\x1b[33m",  # жёлтый
}


def colorize(message: str, level: str = "info") -> str:
    level = level.lower()
    color = COLORS.get(level, "")
    if not color:
        return message
    return f"{color}{message}{RESET}"