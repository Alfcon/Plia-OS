import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_timers_returns_only_timers(app):
    mock = MagicMock()
    mock.list_pending.return_value = [
        {"id": 1, "message": "Timer done!", "fire_at": "2026-06-16T10:00:00", "is_timer": True},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/timers")
    assert r.status_code == 200
    mock.list_pending.assert_called_once_with(timers_only=True)
    data = r.json()
    assert len(data) == 1
    assert data[0]["is_timer"] is True


@pytest.mark.asyncio
async def test_list_timers_empty(app):
    mock = MagicMock()
    mock.list_pending.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/timers")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_cancel_timer_marks_done(app):
    mock = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/timers/7")
    assert r.status_code == 200
    assert r.json() == {"status": "cancelled", "id": 7}
    mock.mark_reminder_done.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_reminders_excludes_timers(app):
    mock = MagicMock()
    mock.list_pending.return_value = [
        {"id": 2, "message": "Call dentist", "fire_at": "2026-06-16T14:00:00", "is_timer": False},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/reminders")
    # list_pending called without timers_only (default False = reminders only)
    mock.list_pending.assert_called_once_with()
