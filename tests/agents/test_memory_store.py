import pytest
from agents.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db = str(tmp_path / "memory.db")
    chroma = str(tmp_path / "chroma")
    return MemoryStore(db_path=db, chroma_path=chroma)


def test_remember_and_get_fact(store):
    store.remember("user.name", "Alfcon")
    assert store.get_fact("user.name") == "Alfcon"


def test_remember_overwrites_existing(store):
    store.remember("key", "first")
    store.remember("key", "second")
    assert store.get_fact("key") == "second"


def test_forget_removes_fact(store):
    store.remember("key", "value")
    store.forget("key")
    assert store.get_fact("key") is None


def test_forget_nonexistent_is_safe(store):
    store.forget("does_not_exist")  # must not raise


def test_list_all_returns_all_facts(store):
    store.remember("user.name", "Alfcon")
    store.remember("user.dog", "Rex")
    facts = store.list_all()
    keys = [f["key"] for f in facts]
    assert "user.name" in keys
    assert "user.dog" in keys
    assert all("key" in f and "value" in f for f in facts)


def test_list_all_empty(store):
    assert store.list_all() == []


def test_list_all_reflects_overwrite(store):
    store.remember("k", "first")
    store.remember("k", "second")
    facts = store.list_all()
    assert len(facts) == 1
    assert facts[0]["value"] == "second"


def test_add_turn_and_recall_fallback(store):
    store.add_turn("user", "what is the weather")
    store.add_turn("assistant", "it is sunny")
    results = store.recall("weather")
    assert any("weather" in r or "sunny" in r for r in results)


def test_history_pruned_at_cap(store):
    for i in range(510):
        store.add_turn("user", f"message {i}")
    import sqlite3
    with sqlite3.connect(store._db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    assert count <= 500


def test_recall_returns_list(store):
    results = store.recall("anything")
    assert isinstance(results, list)
