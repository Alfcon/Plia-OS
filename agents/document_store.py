from __future__ import annotations
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_store: "_DocumentStore | None" = None


def get_document_store() -> "_DocumentStore":
    global _store
    if _store is None:
        from core.config import get_config
        _store = _DocumentStore(get_config().memory_dir)
    return _store


class _DocumentStore:
    def __init__(self, memory_dir: str) -> None:
        self._dir = Path(memory_dir) / "doc_index"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self._ready = False
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._dir))
            self._collection = self._client.get_or_create_collection("documents")
            self._ready = True
        except Exception as exc:
            logger.warning("ChromaDB unavailable for document store: %s", exc)

    # ------------------------------------------------------------------
    def index_directory(self, directory: str, glob: str = "*.txt") -> str:
        if not self._ready:
            return "ChromaDB unavailable — document indexing disabled."
        from pathlib import Path as P
        root = P(directory).expanduser()
        if not root.is_dir():
            return f"Directory not found: {directory}"
        pattern = glob or "**/*"
        files = list(root.glob(pattern)) if "**" in pattern else list(root.rglob(glob))
        if not files:
            return f"No files matched '{glob}' in {directory}"
        added = 0
        errors = []
        for f in files:
            try:
                text = _read_file_text(f)
                if not text.strip():
                    continue
                doc_id = str(f.resolve())
                chunks = _chunk(text)
                ids = [f"{doc_id}::{i}" for i in range(len(chunks))]
                metas = [{"source": doc_id, "chunk": i} for i in range(len(chunks))]
                self._collection.upsert(documents=chunks, ids=ids, metadatas=metas)
                added += len(chunks)
            except Exception as exc:
                errors.append(f"{f.name}: {exc}")
        msg = f"Indexed {len(files)} file(s) → {added} chunk(s)."
        if errors:
            msg += f" Errors: {'; '.join(errors[:3])}"
        return msg

    def query(self, text: str, n_results: int = 5) -> str:
        if not self._ready:
            return "ChromaDB unavailable — document search disabled."
        try:
            res = self._collection.query(query_texts=[text], n_results=max(1, n_results))
        except Exception as exc:
            return f"Query failed: {exc}"
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        if not docs:
            return "No relevant documents found."
        parts = []
        for doc, meta in zip(docs, metas):
            src = Path(meta.get("source", "?")).name
            parts.append(f"[{src}] {doc[:400]}")
        return "\n\n---\n\n".join(parts)

    def list_sources(self) -> list[str]:
        if not self._ready:
            return []
        try:
            all_metas = self._collection.get(include=["metadatas"])["metadatas"]
            return sorted({m["source"] for m in all_metas if m.get("source")})
        except Exception:
            return []

    def delete_source(self, source_path: str) -> int:
        if not self._ready:
            return 0
        try:
            all_items = self._collection.get(include=["metadatas"])
            ids_to_del = [
                id_ for id_, meta in zip(all_items["ids"], all_items["metadatas"])
                if meta.get("source") == source_path
            ]
            if ids_to_del:
                self._collection.delete(ids=ids_to_del)
            return len(ids_to_del)
        except Exception:
            return 0


def _read_file_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            pass
    elif ext == ".docx":
        try:
            import docx as _docx
            doc = _docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            pass
    elif ext in (".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml"):
        return path.read_text(errors="replace")
    return ""


def _chunk(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + size])
        chunks.append(chunk)
        i += size - overlap
    return chunks or [text]
