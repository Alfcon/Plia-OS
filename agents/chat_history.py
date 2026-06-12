from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "chat_history.db"
_DB_PATH.parent.mkdir(exist_ok=True)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            role    TEXT NOT NULL,
            content TEXT NOT NULL,
            ts      TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def add_message(role: str, content: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO messages (role, content, ts) VALUES (?, ?, ?)",
            (role, content, datetime.now(timezone.utc).isoformat()),
        )


def get_recent(n: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT role, content, ts FROM messages ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [{"role": r, "content": c, "ts": t} for r, c, t in reversed(rows)]


def clear() -> None:
    with _conn() as con:
        con.execute("DELETE FROM messages")
        con.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
