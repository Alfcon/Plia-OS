import time
import pytest
from agents.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(str(tmp_path / "m.db"), str(tmp_path / "chroma"))


def _connect(store, jane_edges=2):
    j = store.upsert_entity("Jane", "person")
    a = store.upsert_entity("Acme", "organization")
    store.add_edge(j, "works_at", a)
    if jane_edges >= 2:
        p = store.upsert_entity("Q3 project", "project")
        store.add_edge(j, "manages", p)
    return j


def test_needing_synthesis_respects_min_edges(store):
    store.upsert_entity("Lonely", "person")   # 0 edges
    _connect(store, jane_edges=2)             # Jane=2, Acme=1, project=1
    names = {e["name"] for e in store.entities_needing_synthesis(min_edges=2)}
    assert names == {"Jane"}                  # only Jane has >=2 edges


def test_needing_synthesis_excludes_fresh_summary(store):
    j = _connect(store, jane_edges=2)
    store.set_entity_summary(j, "Jane works at Acme and manages Q3.")
    # summary_at is now >= updated_at, so Jane is no longer a candidate
    assert store.entities_needing_synthesis(min_edges=2) == []


def test_needing_synthesis_reincludes_after_change(store):
    j = _connect(store, jane_edges=2)
    store.set_entity_summary(j, "old summary")
    time.sleep(0.01)
    # a new edge upserts Jane again -> updated_at advances beyond summary_at
    o = store.upsert_entity("Bob", "person")
    store.add_edge(j, "knows", o)
    names = {e["name"] for e in store.entities_needing_synthesis(min_edges=2)}
    assert "Jane" in names


def test_set_entity_summary_does_not_touch_updated_at(store):
    j = _connect(store, jane_edges=2)
    with store._conn() as conn:
        before = conn.execute("SELECT updated_at FROM entities WHERE id=?", (j,)).fetchone()[0]
    time.sleep(0.01)
    store.set_entity_summary(j, "a summary")
    with store._conn() as conn:
        after = conn.execute("SELECT updated_at FROM entities WHERE id=?", (j,)).fetchone()[0]
    assert before == after                    # summary write must not bump updated_at


def test_graph_entity_includes_summary(store):
    j = _connect(store, jane_edges=2)
    store.set_entity_summary(j, "Jane summary.")
    g = store.graph_entity("Jane")
    assert g["summary"] == "Jane summary."
    # entity without a summary -> None
    assert store.graph_entity("Acme")["summary"] is None
