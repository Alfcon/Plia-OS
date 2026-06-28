from __future__ import annotations
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_HISTORY_PRELOAD = 20  # turns loaded into context on startup / per chat request

_DB_PATH = Path(__file__).parent.parent / "data" / "chat_history.db"
_DB_PATH.parent.mkdir(exist_ok=True)


def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH)
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                role    TEXT NOT NULL,
                content TEXT NOT NULL,
                ts      TEXT NOT NULL
            )
        """)
        con.commit()
    finally:
        con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH)


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


def search(query: str, n: int = 50) -> list[dict]:
    if not query:
        return []
    pattern = f"%{query}%"
    with _conn() as con:
        rows = con.execute(
            "SELECT role, content, ts FROM messages WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (pattern, n),
        ).fetchall()
    return [{"role": r, "content": c, "ts": t} for r, c, t in rows]


def clear() -> None:
    rows = get_recent(n=10000)
    if rows:
        try:
            from agents.memory_store import get_memory_store
            now = datetime.now(timezone.utc).isoformat()
            text = "\n".join(f"[{m['ts']}] {m['role']}: {m['content']}" for m in rows)
            get_memory_store().remember(f"chat_archive_{now}", text)
        except Exception:
            logger.warning("Chat archive failed; proceeding with delete", exc_info=True)
    with _conn() as con:
        con.execute("DELETE FROM messages")
        con.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
