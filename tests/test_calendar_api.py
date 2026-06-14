import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_calendar_events_returns_list(app):
    mock_store = MagicMock()
    mock_store.list_events_json.return_value = [
        {"uid": "abc-123", "title": "Meeting", "dtstart": "2026-06-15T10:00:00", "dtend": "2026-06-15T11:00:00"}
    ]
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/calendar")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["title"] == "Meeting"


@pytest.mark.asyncio
async def test_create_calendar_event_returns_uid(app):
    mock_store = MagicMock()
    mock_store.add_event.return_value = "uid-xyz"
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/calendar", json={
                "title": "Dentist",
                "date": "2026-06-20",
                "time": "14:00",
                "duration_min": 30,
            })
    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == "uid-xyz"
    assert body["title"] == "Dentist"


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_missing_title(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/calendar", json={"date": "2026-06-20"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_missing_date(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/calendar", json={"title": "No date event"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_calendar_event_success(app):
    mock_store = MagicMock()
    mock_store.delete_event.return_value = True
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/calendar/uid-xyz")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert r.json()["uid"] == "uid-xyz"


@pytest.mark.asyncio
async def test_delete_calendar_event_not_found(app):
    mock_store = MagicMock()
    mock_store.delete_event.return_value = False
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/calendar/no-such-uid")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_invalid_date(app):
    mock_store = MagicMock()
    mock_store.add_event.side_effect = ValueError("Invalid date/time: '2026-13-45 09:00'")
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/calendar", json={"title": "Bad", "date": "2026-13-45"})
    assert r.status_code == 422
