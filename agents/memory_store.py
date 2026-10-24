from __future__ import annotations
import os
import sqlite3
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

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
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    type TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    object_id INTEGER NOT NULL,
                    source_fact TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(subject_id, relation, object_id)
                );
            """)
            try:
                conn.execute("ALTER TABLE reminders ADD COLUMN is_timer INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            for _col in ("summary TEXT", "summary_at TEXT"):
                try:
                    conn.execute(f"ALTER TABLE entities ADD COLUMN {_col}")
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

    def search_facts(self, query: str, n: int = 50) -> list[dict]:
        pattern = f"%{query}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, pattern, n),
            ).fetchall()
        return [{"key": r[0], "value": r[1]} for r in rows]

    def search_reminders(self, query: str, n: int = 50) -> list[dict]:
        pattern = f"%{query}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, message, fire_at, done, is_timer FROM reminders WHERE message LIKE ? ORDER BY fire_at DESC LIMIT ?",
                (pattern, n),
            ).fetchall()
        return [{"id": r[0], "message": r[1], "fire_at": r[2], "done": bool(r[3]), "is_timer": bool(r[4])} for r in rows]

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

    def snooze_reminder(self, reminder_id: int, minutes: int) -> bool:
        from datetime import datetime, timezone, timedelta
        new_fire_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE reminders SET fire_at=?, done=0 WHERE id=?",
                (new_fire_at, reminder_id),
            )
            return cur.rowcount > 0

    def mark_reminder_done(self, reminder_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))

    def clear_pending_reminders(self) -> int:
        """Mark every pending reminder done. Returns how many were cleared.

        Mirrors delete_reminder's semantics (mark done, don't DELETE) and
        list_pending's scope: timers live in this table under is_timer=1 and
        are cancelled separately, so they are left running.
        """
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE reminders SET done=1 WHERE done=0 AND is_timer=0"
            )
            return cur.rowcount

    def delete_done_reminders(self) -> int:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM reminders WHERE done=1")
            return cur.rowcount

    def bulk_snooze_reminders(self, ids: list, minutes: int) -> int:
        new_fire_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        with self._conn() as conn:
            count = 0
            for rid in ids:
                cur = conn.execute(
                    "UPDATE reminders SET fire_at=?, done=0 WHERE id=?",
                    (new_fire_at, int(rid)),
                )
                count += cur.rowcount
            return count

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

    # ── Knowledge graph ──────────────────────────────────────────────────────
    def upsert_entity(self, name: str, type: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO entities (name, type, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET type=excluded.type, updated_at=excluded.updated_at",
                (name, type, now),
            )
            row = conn.execute(
                "SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        return row[0]

    def add_edge(self, subject_id: int, relation: str, object_id: int, source: str = "") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO edges "
                "(subject_id, relation, object_id, source_fact, updated_at) VALUES (?, ?, ?, ?, ?)",
                (subject_id, relation, object_id, source, now),
            )
            # If edge was actually inserted (new edge), bump updated_at on both entities
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE entities SET updated_at = ? WHERE id IN (?, ?)",
                    (now, subject_id, object_id),
                )
            return cur.rowcount > 0

    def graph_entity(self, name: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, type, summary FROM entities WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if row is None:
                return None
            eid, ename, etype, esummary = row
            out_rows = conn.execute(
                "SELECT e.relation, o.name FROM edges e JOIN entities o ON o.id = e.object_id "
                "WHERE e.subject_id = ?",
                (eid,),
            ).fetchall()
            in_rows = conn.execute(
                "SELECT e.relation, s.name FROM edges e JOIN entities s ON s.id = e.subject_id "
                "WHERE e.object_id = ?",
                (eid,),
            ).fetchall()
        edges = [{"relation": r, "other": o, "direction": "out"} for r, o in out_rows]
        edges += [{"relation": r, "other": s, "direction": "in"} for r, s in in_rows]
        return {"name": ename, "type": etype, "summary": esummary, "edges": edges}

    def sparse_entities(self, max_edges: int = 1) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT en.name, en.type, "
                "  (SELECT COUNT(*) FROM edges e WHERE e.subject_id = en.id OR e.object_id = en.id) AS cnt "
                "FROM entities en ORDER BY cnt ASC, en.name ASC"
            ).fetchall()
        return [{"name": r[0], "type": r[1], "edge_count": r[2]} for r in rows if r[2] <= max_edges]

    def all_entities(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT name, type FROM entities ORDER BY name ASC").fetchall()
        return [{"name": r[0], "type": r[1]} for r in rows]

    def entities_needing_synthesis(self, min_edges: int = 2) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT en.id, en.name, en.type, "
                "  (SELECT COUNT(*) FROM edges e WHERE e.subject_id = en.id OR e.object_id = en.id) AS cnt "
                "FROM entities en "
                "WHERE en.summary_at IS NULL OR en.updated_at > en.summary_at "
                "ORDER BY cnt DESC"
            ).fetchall()
        return [{"id": r[0], "name": r[1], "type": r[2]} for r in rows if r[3] >= min_edges]

    def set_entity_summary(self, entity_id: int, summary: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE entities SET summary = ?, summary_at = ? WHERE id = ?",
                (summary, now, entity_id),
            )


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
