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
    return get_recent_with_id(n, include_id=False)


def get_recent_with_id(n: int = 100, include_id: bool = False) -> list[dict]:
    with _conn() as con:
        cols = "id, role, content, ts" if include_id else "role, content, ts"
        rows = con.execute(
            f"SELECT {cols} FROM messages ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    if include_id:
        return [{"id": r, "role": r2, "content": c, "ts": t} for r, r2, c, t in reversed(rows)]
    return [{"role": r, "content": c, "ts": t} for r, c, t in reversed(rows)]


def get_message_pair(message_id: int) -> tuple[dict, dict] | None:
    """Return (user_msg, assistant_msg) for an assistant message id.

    None if the id is unknown, is not an assistant message, or has no
    preceding user message — a rating needs both halves of the exchange.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT id, role, content FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row or row[1] != "assistant":
            return None
        prev = con.execute(
            "SELECT id, role, content FROM messages "
            "WHERE id < ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (message_id,),
        ).fetchone()
    if not prev:
        return None
    return (
        {"id": prev[0], "role": prev[1], "content": prev[2]},
        {"id": row[0], "role": row[1], "content": row[2]},
    )


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


def clear_permanent() -> None:
    """Delete all chat history with no archiving."""
    with _conn() as con:
        con.execute("DELETE FROM messages")
        con.execute("DELETE FROM sqlite_sequence WHERE name='messages'")


def delete_message(message_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        return cur.rowcount > 0
