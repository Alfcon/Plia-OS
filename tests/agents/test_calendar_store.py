import pytest
import os
from agents.calendar_store import CalendarStore, reset_calendar_store


@pytest.fixture
def store(tmp_path):
    reset_calendar_store()
    return CalendarStore(ics_path=str(tmp_path / "calendar.ics"))


def test_store_creates_ics_file(tmp_path):
    path = str(tmp_path / "cal.ics")
    CalendarStore(ics_path=path)
    assert os.path.exists(path)


def test_add_event_returns_uid(store):
    uid = store.add_event("Team meeting", "2026-07-01", "10:00", 60)
    assert isinstance(uid, str)
    assert len(uid) > 0


def test_list_events_shows_added_event(store):
    store.add_event("Doctor appointment", "2026-07-02", "14:00", 30)
    events = store.list_events()
    assert any("Doctor appointment" in e for e in events)


def test_list_events_empty_returns_no_events(store):
    events = store.list_events()
    assert events == ["No events found"]


def test_delete_event_removes_it(store):
    uid = store.add_event("To delete", "2026-07-03", "09:00", 15)
    deleted = store.delete_event(uid)
    assert deleted is True
    events = store.list_events()
    assert not any("To delete" in e for e in events)


def test_delete_nonexistent_returns_false(store):
    result = store.delete_event("00000000-0000-0000-0000-000000000000")
    assert result is False


def test_multiple_events_all_listed(store):
    store.add_event("Event A", "2026-07-01", "09:00", 30)
    store.add_event("Event B", "2026-07-02", "10:00", 60)
    events = store.list_events()
    assert len(events) == 2
    assert any("Event A" in e for e in events)
    assert any("Event B" in e for e in events)


def test_event_includes_date_in_listing(store):
    store.add_event("Birthday party", "2026-08-15", "18:00", 120)
    events = store.list_events()
    assert any("2026-08-15" in e for e in events)
