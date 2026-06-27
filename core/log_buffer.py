from __future__ import annotations

import collections
import logging
import threading
import time

_CAPACITY = 1000

_LEVEL_NAMES = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}


class LogBuffer(logging.Handler):
    """Thread-safe in-memory ring buffer for log records."""

    def __init__(self, capacity: int = _CAPACITY) -> None:
        super().__init__(level=logging.DEBUG)
        self._buf: collections.deque[dict] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": record.created,
            "level": _LEVEL_NAMES.get(record.levelno, record.levelname),
            "levelno": record.levelno,
            "name": record.name,
            "msg": self.format(record),
        }
        with self._lock:
            self._buf.append(entry)

    def get(self, n: int = 200, min_level: int = logging.DEBUG) -> list[dict]:
        with self._lock:
            records = list(self._buf)
        filtered = [r for r in records if r["levelno"] >= min_level]
        return filtered[-n:]

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


_instance: LogBuffer | None = None
_install_lock = threading.Lock()


def get_log_buffer() -> LogBuffer:
    global _instance
    if _instance is None:
        with _install_lock:
            if _instance is None:
                _instance = LogBuffer()
    return _instance


def install() -> LogBuffer:
    buf = get_log_buffer()
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, LogBuffer):
            return buf
    fmt = logging.Formatter("%(name)s: %(message)s")
    buf.setFormatter(fmt)
    root.addHandler(buf)
    return buf
