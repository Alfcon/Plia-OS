import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_notes_empty(app):
    mock = MagicMock()
    mock.list_all.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/notes")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_notes_returns_only_notes(app):
    mock = MagicMock()
    mock.list_all.return_value = [
        {"key": "note_20260616_120000", "value": "buy milk"},
        {"key": "user_name", "value": "Alice"},
        {"key": "note_20260616_130000", "value": "call dentist"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/notes")
    data = r.json()
    assert len(data) == 2
    assert all(item["key"].startswith("note_") for item in data)


@pytest.mark.asyncio
async def test_create_note_returns_key_and_value(app):
    mock = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/notes", json={"text": "pick up kids"})
    assert r.status_code == 200
    data = r.json()
    assert data["value"] == "pick up kids"
    assert data["key"].startswith("note_")
    mock.remember.assert_called_once()


@pytest.mark.asyncio
async def test_create_note_empty_text_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/notes", json={"text": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_note_missing_text_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/notes", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_note(app):
    mock = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.delete("/api/notes/note_20260616_120000")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    mock.forget.assert_called_once_with("note_20260616_120000")


@pytest.mark.asyncio
async def test_update_note_stores_new_text(app):
    mock = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/notes/note_20260616_120000", json={"text": "buy oat milk"})
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == "note_20260616_120000"
    assert data["value"] == "buy oat milk"
    mock.remember.assert_called_once_with("note_20260616_120000", "buy oat milk")


@pytest.mark.asyncio
async def test_update_note_empty_text_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.put("/api/notes/note_20260616_120000", json={"text": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_memory_api_excludes_notes(app):
    mock = MagicMock()
    mock.list_all.return_value = [
        {"key": "note_20260616_120000", "value": "buy milk"},
        {"key": "user_name", "value": "Alice"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/memory")
    data = r.json()
    assert len(data) == 1
    assert data[0]["key"] == "user_name"
