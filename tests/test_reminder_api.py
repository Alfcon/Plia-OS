import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_create_reminder_returns_id(app):
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 99
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/reminders", json={
                "message": "Take vitamins",
                "fire_at": "2026-06-14T09:00:00+00:00",
            })
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 99
    assert body["message"] == "Take vitamins"


@pytest.mark.asyncio
async def test_create_reminder_rejects_missing_fields(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/reminders", json={"message": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_reminder_rejects_blank_fire_at(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/reminders", json={"message": "Test", "fire_at": ""})
    assert r.status_code == 422
