from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_CAP = 5000


def _db_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir).expanduser() / "event_log.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    return c


def _init() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL    NOT NULL,
                event_type TEXT    NOT NULL,
                data       TEXT    NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")


def log_event(payload: dict) -> None:
    event_type = payload.get("type", "unknown")
    ts = time.time()
    data = json.dumps(payload)
    with _lock, _conn() as c:
        c.execute("INSERT INTO events (ts, event_type, data) VALUES (?, ?, ?)", (ts, event_type, data))
        # rolling cap — delete oldest beyond _CAP
        c.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id DESC LIMIT -1 OFFSET ?)", (_CAP,))


def get_events(n: int = 200, event_type: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        if event_type:
            rows = c.execute(
                "SELECT ts, event_type, data FROM events WHERE event_type=? ORDER BY id DESC LIMIT ?",
                (event_type, n),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT ts, event_type, data FROM events ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
    result = []
    for row in rows:
        try:
            d = json.loads(row["data"])
        except Exception:
            d = {}
        result.append({"ts": row["ts"], "event_type": row["event_type"], "data": d})
    return result


def clear_events() -> int:
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM events")
        return cur.rowcount


def get_event_types() -> list[str]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT DISTINCT event_type FROM events ORDER BY event_type").fetchall()
    return [r["event_type"] for r in rows]


_init()
