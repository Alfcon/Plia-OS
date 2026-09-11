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


def test_init_db_idempotent_with_is_timer_column(store):
    # second call must not raise even though is_timer column already exists
    store._init_db()
    store._init_db()
    future = (_now() + timedelta(minutes=5)).isoformat()
    store.add_reminder("sanity", future)
    assert store.list_pending()[0]["message"] == "sanity"


def test_list_pending_excludes_timers_by_default(store):
    future = (_now() + timedelta(minutes=5)).isoformat()
    store.add_reminder("Call dentist", future, is_timer=False)
    store.add_reminder("Timer done!", future, is_timer=True)
    reminders = store.list_pending()
    assert len(reminders) == 1
    assert reminders[0]["message"] == "Call dentist"
    assert reminders[0]["is_timer"] is False


def test_list_pending_timers_only(store):
    future = (_now() + timedelta(minutes=5)).isoformat()
    store.add_reminder("Call dentist", future, is_timer=False)
    store.add_reminder("Timer done!", future, is_timer=True)
    timers = store.list_pending(timers_only=True)
    assert len(timers) == 1
    assert timers[0]["message"] == "Timer done!"
    assert timers[0]["is_timer"] is True


def test_is_timer_flag_stored_correctly(store):
    future = (_now() + timedelta(minutes=5)).isoformat()
    store.add_reminder("reminder", future, is_timer=False)
    store.add_reminder("timer", future, is_timer=True)
    with store._conn() as conn:
        rows = conn.execute("SELECT message, is_timer FROM reminders ORDER BY id").fetchall()
    assert rows[0] == ("reminder", 0)
    assert rows[1] == ("timer", 1)
