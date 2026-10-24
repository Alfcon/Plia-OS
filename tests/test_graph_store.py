import pytest
from agents.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(str(tmp_path / "m.db"), str(tmp_path / "chroma"))


def test_upsert_entity_dedups_case_insensitive(store):
    a = store.upsert_entity("Jane", "person")
    b = store.upsert_entity("jane", "person")
    assert a == b                                   # same id regardless of case
    assert len(store.all_entities()) == 1


def test_upsert_entity_updates_type(store):
    store.upsert_entity("Acme", "thing")
    store.upsert_entity("Acme", "organization")
    ents = {e["name"].lower(): e["type"] for e in store.all_entities()}
    assert ents["acme"] == "organization"


def test_add_edge_dedups_triple(store):
    j = store.upsert_entity("Jane", "person")
    a = store.upsert_entity("Acme", "organization")
    assert store.add_edge(j, "works_at", a, "Jane works at Acme") is True
    assert store.add_edge(j, "works_at", a, "again") is False   # duplicate triple


def test_graph_entity_both_directions(store):
    j = store.upsert_entity("Jane", "person")
    a = store.upsert_entity("Acme", "organization")
    p = store.upsert_entity("Q3 project", "project")
    store.add_edge(j, "works_at", a)         # Jane -> Acme (out for Jane)
    store.add_edge(j, "manages", p)          # Jane -> project (out for Jane)
    g = store.graph_entity("jane")
    assert g["type"] == "person"
    rels = {(e["relation"], e["other"], e["direction"]) for e in g["edges"]}
    assert ("works_at", "Acme", "out") in rels
    assert ("manages", "Q3 project", "out") in rels
    # Acme sees the inbound edge
    ga = store.graph_entity("Acme")
    assert ("works_at", "Jane", "in") in {(e["relation"], e["other"], e["direction"]) for e in ga["edges"]}


def test_graph_entity_unknown_returns_none(store):
    assert store.graph_entity("Nobody") is None


def test_sparse_entities_threshold(store):
    j = store.upsert_entity("Jane", "person")
    a = store.upsert_entity("Acme", "organization")
    store.upsert_entity("Orphan", "thing")   # 0 edges
    store.add_edge(j, "works_at", a)
    # Jane=1 edge, Acme=1 edge, Orphan=0 edges
    sparse = {e["name"] for e in store.sparse_entities(max_edges=0)}
    assert sparse == {"Orphan"}
    sparse1 = {e["name"] for e in store.sparse_entities(max_edges=1)}
    assert sparse1 == {"Jane", "Acme", "Orphan"}
