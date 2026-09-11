from __future__ import annotations
import sqlite3
import threading
from pathlib import Path

from core.config import get_config

_lock = threading.Lock()
_store: "_CronStore | None" = None


def get_cron_store() -> "_CronStore":
    global _store
    if _store is None:
        _store = _CronStore()
    return _store


class _CronStore:
    def __init__(self) -> None:
        db_dir = Path(get_config().memory_dir).expanduser()
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db = db_dir / "cron.db"
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with _lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crons (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name    TEXT    NOT NULL UNIQUE,
                    expr    TEXT    NOT NULL,
                    message TEXT    NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
            """)

    def add(self, name: str, expr: str, message: str) -> int:
        with _lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT OR REPLACE INTO crons (name, expr, message, enabled) VALUES (?, ?, ?, 1)",
                (name, expr, message),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def remove(self, name: str) -> bool:
        with _lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM crons WHERE name = ?", (name,))
            return cur.rowcount > 0

    def set_enabled(self, name: str, enabled: bool) -> bool:
        with _lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE crons SET enabled = ? WHERE name = ?",
                (1 if enabled else 0, name),
            )
            return cur.rowcount > 0

    def list_all(self) -> list[dict]:
        with _lock, self._conn() as conn:
            rows = conn.execute("SELECT id, name, expr, message, enabled FROM crons").fetchall()
            return [dict(r) for r in rows]

    def list_enabled(self) -> list[dict]:
        with _lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT id, name, expr, message FROM crons WHERE enabled = 1"
            ).fetchall()
            return [dict(r) for r in rows]
