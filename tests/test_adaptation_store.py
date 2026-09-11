from __future__ import annotations
import pytest
from agents.adaptation import AdaptationStore


class FakeCollection:
    """Stands in for a Chroma collection. Records adds; returns canned query hits."""

    def __init__(self):
        self.docs: list[tuple[str, str, dict]] = []  # (id, document, metadata)
        self.deleted: list[str] = []
        self.query_hits: list[tuple[int, float]] = []  # (row_id, distance)

    def add(self, documents, ids, metadatas):
        for d, i, m in zip(documents, ids, metadatas):
            self.docs.append((i, d, m))

    def query(self, query_texts, n_results, where=None):
        self.last_where = where
        hits = self.query_hits[:n_results]
        return {
            "ids": [[f"ex_{rid}" for rid, _ in hits]],
            "distances": [[dist for _, dist in hits]],
            "metadatas": [[{"row_id": rid} for rid, _ in hits]],
        }

    def delete(self, ids):
        self.deleted.extend(ids)


@pytest.fixture
def store(tmp_path):
    """Store with Chroma disabled — SQLite-only behaviour."""
    s = AdaptationStore(str(tmp_path / "adaptation.db"), str(tmp_path / "chroma"))
    s._collection = None
    s._ef = None
    return s


@pytest.fixture
def store_with_chroma(store):
    store._collection = FakeCollection()
    return store


def test_add_intent_correction_roundtrip(store):
    rid = store.add_intent_correction("turn the lamp on", "home")
    rows = store.list_exemplars()
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["utterance"] == "turn the lamp on"
    assert rows[0]["intent"] == "home"
    assert rows[0]["rating"] == 1
    assert rows[0]["source"] == "chat"


def test_add_style_exemplar_roundtrip(store):
    rid = store.add_style_exemplar("what's the time", "3pm.", 1, "thumb")
    rows = store.list_exemplars()
    assert rows[0]["id"] == rid
    assert rows[0]["response"] == "3pm."
    assert rows[0]["intent"] is None


def test_chroma_absent_retrieval_returns_empty_but_writes_succeed(store):
    store.add_intent_correction("turn the lamp on", "home")
    assert store.retrieve_intent_examples("turn the lamp on") == []
    assert store.retrieve_style_examples("turn the lamp on") == []
    assert len(store.list_exemplars()) == 1


def test_negative_style_exemplar_is_stored_but_never_indexed(store_with_chroma):
    # THE SAFETY RULE: noisy signals may exclude, never teach.
    store_with_chroma.add_style_exemplar("do the thing", "a bad answer", -1, "thumb")
    assert len(store_with_chroma.list_exemplars()) == 1
    assert store_with_chroma._collection.docs == []  # not indexed


def test_positive_style_exemplar_is_indexed(store_with_chroma):
    rid = store_with_chroma.add_style_exemplar("do the thing", "a good answer", 1, "thumb")
    assert len(store_with_chroma._collection.docs) == 1
    doc_id, doc, meta = store_with_chroma._collection.docs[0]
    assert doc == "do the thing"
    assert meta["row_id"] == rid
    assert meta["kind"] == "style"
    assert meta["rating"] == 1


def test_retrieve_intent_examples_joins_back_to_sqlite(store_with_chroma):
    rid = store_with_chroma.add_intent_correction("turn the lamp on", "home")
    store_with_chroma._collection.query_hits = [(rid, 0.04)]
    out = store_with_chroma.retrieve_intent_examples("turn on the lamp")
    assert len(out) == 1
    assert out[0]["utterance"] == "turn the lamp on"
    assert out[0]["intent"] == "home"
    assert out[0]["similarity"] == pytest.approx(0.96)


def test_retrieve_filters_on_kind_and_rating(store_with_chroma):
    store_with_chroma.retrieve_intent_examples("x")
    assert store_with_chroma._collection.last_where == {
        "$and": [{"kind": "intent"}, {"rating": 1}]
    }


def test_retrieve_skips_rows_deleted_from_sqlite(store_with_chroma):
    # Chroma is a disposable index; a stale hit must not crash or fabricate a row.
    store_with_chroma._collection.query_hits = [(999, 0.01)]
    assert store_with_chroma.retrieve_intent_examples("x") == []


def test_retrieve_survives_chroma_raising(store_with_chroma):
    def boom(*a, **k):
        raise RuntimeError("chroma down")
    store_with_chroma._collection.query = boom
    assert store_with_chroma.retrieve_intent_examples("x") == []


def test_delete_exemplar(store_with_chroma):
    rid = store_with_chroma.add_intent_correction("x", "home")
    assert store_with_chroma.delete_exemplar(rid) is True
    assert store_with_chroma.list_exemplars() == []
    assert store_with_chroma._collection.deleted == [f"ex_{rid}"]
    assert store_with_chroma.delete_exemplar(rid) is False


def test_delete_survives_chroma_raising(store_with_chroma):
    rid = store_with_chroma.add_intent_correction("x", "home")
    def boom(*a, **k):
        raise RuntimeError("chroma down")
    store_with_chroma._collection.delete = boom
    assert store_with_chroma.delete_exemplar(rid) is True  # SQLite delete stands
    assert store_with_chroma.list_exemplars() == []


def test_has_rephrase(store):
    assert store.has_rephrase("say it again") is False
    store.add_style_exemplar("say it again", "resp", -1, "rephrase")
    assert store.has_rephrase("say it again") is True


def test_similarity_none_without_embeddings(store):
    assert store.similarity("a", "b") is None


def test_similarity_computes_cosine(store):
    store._ef = lambda texts: [[1.0, 0.0], [1.0, 0.0]]
    assert store.similarity("a", "a") == pytest.approx(1.0)
    store._ef = lambda texts: [[1.0, 0.0], [0.0, 1.0]]
    assert store.similarity("a", "b") == pytest.approx(0.0)


def test_clear(store_with_chroma):
    store_with_chroma.add_intent_correction("x", "home")
    store_with_chroma.clear()
    assert store_with_chroma.list_exemplars() == []


def test_list_exemplars_newest_first(store):
    store.add_intent_correction("first", "home")
    store.add_intent_correction("second", "web")
    rows = store.list_exemplars()
    assert [r["utterance"] for r in rows] == ["second", "first"]
