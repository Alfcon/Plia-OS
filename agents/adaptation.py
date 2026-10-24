"""
Correction-driven adaptation store.

SQLite is the source of truth; Chroma is a disposable semantic index keyed by
row_id. Mirrors agents/memory_store.py: all methods sync (wrap in
asyncio.to_thread from async callers), and every Chroma failure degrades to
empty results rather than raising.

Safety rule: only rating=+1 exemplars are indexed. Negative signals (thumbs
down, rephrase) are stored for the dashboard viewer but can never be
retrieved as examples.
"""
from __future__ import annotations
import math
import os
import sqlite3
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_COLLECTION = "adaptations"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class AdaptationStore:
    def __init__(self, db_path: str, chroma_path: str, ollama_url: str = "http://localhost:11434") -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db_path = db_path
        self._chroma_path = chroma_path
        self._ollama_url = ollama_url
        self._collection = None
        self._ef = None
        self._init_db()
        self._init_chroma()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS exemplars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    utterance TEXT NOT NULL,
                    intent TEXT,
                    response TEXT,
                    rating INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    ts TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_exemplars_rating ON exemplars (rating);
                CREATE INDEX IF NOT EXISTS idx_exemplars_intent ON exemplars (intent);
            """)

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
                _COLLECTION,
                embedding_function=ef,
                # Thresholds in config are cosine; Chroma defaults to L2.
                metadata={"hnsw:space": "cosine"},
            )
            self._ef = ef
        except Exception:
            logger.warning("ChromaDB unavailable; adaptation retrieval disabled", exc_info=True)
            self._collection = None
            self._ef = None

    # ── Write ────────────────────────────────────────────────────────────────
    def _insert(self, utterance: str, intent: str | None, response: str | None,
                rating: int, source: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO exemplars (utterance, intent, response, rating, source, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (utterance, intent, response, rating, source, now),
            )
            return int(cur.lastrowid)

    def add_intent_correction(self, utterance: str, intent: str, source: str = "chat") -> int:
        rid = self._insert(utterance, intent, None, 1, source)
        self._index(rid, utterance, {"kind": "intent", "intent": intent, "rating": 1})
        return rid

    def add_style_exemplar(self, utterance: str, response: str, rating: int, source: str) -> int:
        rid = self._insert(utterance, None, response, rating, source)
        if rating == 1:
            # Safety rule: negatives are stored but never indexed, so they can
            # never come back as an example to imitate.
            self._index(rid, utterance, {"kind": "style", "rating": 1})
        return rid

    def _index(self, row_id: int, utterance: str, metadata: dict) -> None:
        if self._collection is None:
            return
        try:
            self._collection.add(
                documents=[utterance],
                ids=[f"ex_{row_id}"],
                metadatas=[{**metadata, "row_id": row_id}],
            )
        except Exception:
            logger.debug("Chroma index failed for exemplar %s", row_id, exc_info=True)

    # ── Read ─────────────────────────────────────────────────────────────────
    def _query(self, utterance: str, k: int, kind: str) -> list[tuple[int, float]]:
        """Return [(row_id, similarity)] best-first. [] on any failure."""
        if self._collection is None or not utterance or k <= 0:
            return []
        try:
            res = self._collection.query(
                query_texts=[utterance],
                n_results=k,
                where={"$and": [{"kind": kind}, {"rating": 1}]},
            )
        except Exception:
            logger.debug("Chroma query failed", exc_info=True)
            return []
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[tuple[int, float]] = []
        for meta, dist in zip(metas, dists):
            row_id = (meta or {}).get("row_id")
            if row_id is None:
                continue
            out.append((int(row_id), 1.0 - float(dist)))
        return out

    def _retrieve(self, utterance: str, k: int, kind: str, field: str) -> list[dict]:
        """Shared body of the retrieve_* methods: Chroma hits joined back to SQLite.

        `field` is both the SQLite column that must be populated and the key
        the caller reads off each result.
        """
        hits = self._query(utterance, k, kind)
        if not hits:
            return []
        rows = self._fetch(dict(hits).keys())
        out = []
        for row_id, sim in hits:
            row = rows.get(row_id)
            # Chroma is a disposable index — skip hits whose SQLite row is gone.
            if row is None or not row[field]:
                continue
            out.append({"utterance": row["utterance"], field: row[field], "similarity": sim})
        return out

    def retrieve_intent_examples(self, utterance: str, k: int = 3) -> list[dict]:
        return self._retrieve(utterance, k, "intent", "intent")

    def retrieve_style_examples(self, utterance: str, k: int = 3) -> list[dict]:
        return self._retrieve(utterance, k, "style", "response")

    def _fetch(self, row_ids) -> dict[int, dict]:
        ids = list(row_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, utterance, intent, response, rating, source, ts "
                f"FROM exemplars WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return {
            r[0]: {"id": r[0], "utterance": r[1], "intent": r[2], "response": r[3],
                   "rating": r[4], "source": r[5], "ts": r[6]}
            for r in rows
        }

    def has_rephrase(self, utterance: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM exemplars WHERE utterance = ? AND source = 'rephrase' LIMIT 1",
                (utterance,),
            ).fetchone()
        return row is not None

    def similarity(self, a: str, b: str) -> float | None:
        """Cosine similarity between two strings. None if embeddings unavailable."""
        if self._ef is None or not a or not b:
            return None
        try:
            vecs = self._ef([a, b])
            return _cosine(list(vecs[0]), list(vecs[1]))
        except Exception:
            logger.debug("Embedding failed; skipping similarity", exc_info=True)
            return None

    # ── Management ───────────────────────────────────────────────────────────
    def list_exemplars(self, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, utterance, intent, response, rating, source, ts "
                "FROM exemplars ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "utterance": r[1], "intent": r[2], "response": r[3],
             "rating": r[4], "source": r[5], "ts": r[6]}
            for r in rows
        ]

    def delete_exemplar(self, id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM exemplars WHERE id = ?", (id,))
            deleted = cur.rowcount > 0
        if deleted and self._collection is not None:
            try:
                self._collection.delete(ids=[f"ex_{id}"])
            except Exception:
                logger.debug("Chroma delete failed for exemplar %s", id, exc_info=True)
        return deleted

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM exemplars")
        if self._collection is not None:
            try:
                import chromadb
                client = chromadb.PersistentClient(path=self._chroma_path)
                client.delete_collection(_COLLECTION)
                self._init_chroma()
            except Exception:
                logger.warning("Chroma clear failed; adaptation retrieval disabled until restart", exc_info=True)
                self._collection = None
                self._ef = None


_store: AdaptationStore | None = None


def get_adaptation_store() -> AdaptationStore:
    global _store
    if _store is None:
        from core.config import get_config
        config = get_config()
        db_path = os.path.join(config.memory_dir, "adaptation.db")
        chroma_path = os.path.join(config.memory_dir, "chroma")
        _store = AdaptationStore(db_path, chroma_path, config.ollama_url)
    return _store


def reset_adaptation_store() -> None:
    """Test helper — clears the singleton so each test gets a fresh store."""
    global _store
    _store = None
