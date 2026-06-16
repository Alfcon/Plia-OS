from __future__ import annotations
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta

_HISTORY_CAP = 500


class MemoryStore:
    def __init__(self, db_path: str, chroma_path: str, ollama_url: str = "http://localhost:11434") -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db_path = db_path
        self._chroma_path = chroma_path
        self._ollama_url = ollama_url
        self._collection = None
        self._init_db()
        self._init_chroma()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    fire_at TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0
                );
            """)
            try:
                conn.execute("ALTER TABLE reminders ADD COLUMN is_timer INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
            os.makedirs(self._chroma_path, exist_ok=True)
            ef = OllamaEmbeddingFunction(
                url=f"{self._ollama_url}/api/embed",
                model_name="nomic-embed-text",
            )
            client = chromadb.PersistentClient(path=self._chroma_path)
            self._collection = client.get_or_create_collection(
                "conversations",
                embedding_function=ef,
            )
        except Exception:
            self._collection = None

    def remember(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO facts (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )

    def get_fact(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def forget(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM facts WHERE key = ?", (key,))

    def list_all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM facts ORDER BY updated_at DESC",
            ).fetchall()
        return [{"key": r[0], "value": r[1]} for r in rows]

    def add_turn(self, role: str, content: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO history (role, content, ts) VALUES (?, ?, ?)",
                (role, content, now),
            )
            count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            if count > _HISTORY_CAP:
                excess = count - _HISTORY_CAP
                conn.execute(
                    "DELETE FROM history WHERE id IN "
                    "(SELECT id FROM history ORDER BY id ASC LIMIT ?)",
                    (excess,),
                )
        self._chroma_add(role, content)

    def recall(self, query: str, n_results: int = 5) -> list[str]:
        if self._collection is not None:
            try:
                results = self._collection.query(query_texts=[query], n_results=n_results)
                docs = results.get("documents", [[]])[0]
                if docs:
                    return docs
            except Exception:
                pass
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM history ORDER BY id DESC LIMIT ?",
                (n_results,),
            ).fetchall()
        return [f"{r}: {c}" for r, c in reversed(rows)]

    def clear_history(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM history")
        if self._collection is not None:
            try:
                import chromadb
                client = chromadb.PersistentClient(path=self._chroma_path)
                client.delete_collection("conversations")
                self._init_chroma()
            except Exception:
                logger.warning("ChromaDB clear failed; semantic recall disabled until restart", exc_info=True)
                self._collection = None

    def add_reminder(self, message: str, fire_at_iso: str, is_timer: bool = False) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (message, fire_at, done, is_timer) VALUES (?, ?, 0, ?)",
                (message, fire_at_iso, int(is_timer)),
            )
            return cur.lastrowid

    def list_pending(self, timers_only: bool = False) -> list[dict]:
        with self._conn() as conn:
            if timers_only:
                rows = conn.execute(
                    "SELECT id, message, fire_at, is_timer FROM reminders WHERE done=0 AND is_timer=1 ORDER BY fire_at ASC",
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, message, fire_at, is_timer FROM reminders WHERE done=0 AND is_timer=0 ORDER BY fire_at ASC",
                ).fetchall()
        return [{"id": r[0], "message": r[1], "fire_at": r[2], "is_timer": bool(r[3])} for r in rows]

    def get_pending(self) -> list[dict]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, message, fire_at, is_timer FROM reminders WHERE done=0 AND fire_at <= ?",
                (now_iso,),
            ).fetchall()
        return [{"id": r[0], "message": r[1], "fire_at": r[2], "is_timer": bool(r[3])} for r in rows]

    def mark_reminder_done(self, reminder_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))

    def prune_done_reminders(self, older_than_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM reminders WHERE done=1 AND fire_at < ?",
                (cutoff,),
            )
            return cur.rowcount

    def _chroma_add(self, role: str, content: str) -> None:
        if self._collection is None:
            return
        try:
            doc_id = f"{role}_{int(time.time() * 1_000_000)}"
            self._collection.add(documents=[f"{role}: {content}"], ids=[doc_id])
        except Exception:
            pass


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        from core.config import get_config
        config = get_config()
        db_path = os.path.join(config.memory_dir, "memory.db")
        chroma_path = os.path.join(config.memory_dir, "chroma")
        _store = MemoryStore(db_path, chroma_path, config.ollama_url)
    return _store


def reset_memory_store() -> None:
    """Test helper — clears the singleton so each test gets a fresh store."""
    global _store
    _store = None
