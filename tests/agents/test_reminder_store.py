import pytest
from datetime import datetime, timezone, timedelta
from agents.memory_store import MemoryStore, reset_memory_store


@pytest.fixture
def store(tmp_path):
    reset_memory_store()
    return MemoryStore(
        db_path=str(tmp_path / "memory.db"),
        chroma_path=str(tmp_path / "chroma"),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_add_reminder_returns_id(store):
    rid = store.add_reminder("Take meds", (_now() + timedelta(minutes=5)).isoformat())
    assert isinstance(rid, int)
    assert rid > 0


def test_get_pending_returns_overdue(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    store.add_reminder("Overdue task", past)
    pending = store.get_pending()
    assert any(r["message"] == "Overdue task" for r in pending)


def test_get_pending_excludes_future(store):
    future = (_now() + timedelta(hours=1)).isoformat()
    store.add_reminder("Future task", future)
    pending = store.get_pending()
    assert not any(r["message"] == "Future task" for r in pending)


def test_get_pending_excludes_done(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    rid = store.add_reminder("Done task", past)
    store.mark_reminder_done(rid)
    pending = store.get_pending()
    assert not any(r["message"] == "Done task" for r in pending)


def test_mark_reminder_done_sets_flag(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    rid = store.add_reminder("Mark me done", past)
    store.mark_reminder_done(rid)
    with store._conn() as conn:
        row = conn.execute("SELECT done FROM reminders WHERE id=?", (rid,)).fetchone()
    assert row[0] == 1


def test_get_pending_returns_id_and_message(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    store.add_reminder("Check oven", past)
    pending = store.get_pending()
    r = pending[0]
    assert "id" in r and "message" in r
    assert r["message"] == "Check oven"
