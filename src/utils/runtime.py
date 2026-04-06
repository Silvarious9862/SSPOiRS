# src/utils/runtime.py
from __future__ import annotations

import threading
from typing import Dict, Tuple, Any

shutdown_event = threading.Event()

# Реестр клиентов: addr -> {"socket": sock, "thread": thread, "state": str}
clients_lock = threading.Lock()
active_clients: Dict[Tuple[str, int], Dict[str, Any]] = {}