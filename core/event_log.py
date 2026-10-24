from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_CAP = 5000

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         REAL    NOT NULL,
        event_type TEXT    NOT NULL,
        data       TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
    CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
"""

# Path whose schema has already been created in this process. Tracked so a
# runtime change of `memory_dir`, or a deleted DB file, is re-initialised
# instead of raising "no such table: events".
_schema_path: str | None = None


def _db_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir).expanduser() / "event_log.db"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    global _schema_path
    path = str(_db_path())
    if _schema_path == path:
        return
    c.executescript(_SCHEMA)
    _schema_path = path


def _init() -> None:
    with _lock, _conn() as c:
        _ensure_schema(c)


def log_event(payload: dict) -> None:
    event_type = payload.get("type", "unknown")
    ts = time.time()
    data = json.dumps(payload)
    with _lock, _conn() as c:
        _ensure_schema(c)
        c.execute("INSERT INTO events (ts, event_type, data) VALUES (?, ?, ?)", (ts, event_type, data))
        # rolling cap — delete oldest beyond _CAP
        c.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id DESC LIMIT -1 OFFSET ?)", (_CAP,))


def get_events(n: int = 200, event_type: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        _ensure_schema(c)
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
        _ensure_schema(c)
        cur = c.execute("DELETE FROM events")
        return cur.rowcount


def get_event_types() -> list[str]:
    with _lock, _conn() as c:
        _ensure_schema(c)
        rows = c.execute("SELECT DISTINCT event_type FROM events ORDER BY event_type").fetchall()
    return [r["event_type"] for r in rows]


_init()
