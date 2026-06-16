import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_memory_returns_facts(app):
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "user_name", "value": "Alice"},
        {"key": "favorite_color", "value": "blue"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/memory")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["key"] == "user_name"
    assert data[0]["value"] == "Alice"


@pytest.mark.asyncio
async def test_list_memory_empty(app):
    mock_store = MagicMock()
    mock_store.list_all.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/memory")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_delete_memory_calls_forget_and_returns_key(app):
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/memory/user_name")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert r.json()["key"] == "user_name"
    mock_store.forget.assert_called_once_with("user_name")


@pytest.mark.asyncio
async def test_delete_memory_nonexistent_key_returns_200(app):
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/memory/no_such_key")
    assert r.status_code == 200
    mock_store.forget.assert_called_once_with("no_such_key")


@pytest.mark.asyncio
async def test_create_memory_stores_fact(app):
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/memory", json={"key": "user_name", "value": "Alice"})
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == "user_name"
    assert data["value"] == "Alice"
    mock_store.remember.assert_called_once_with("user_name", "Alice")


@pytest.mark.asyncio
async def test_create_memory_missing_key_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/memory", json={"value": "Alice"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_memory_missing_value_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/memory", json={"key": "user_name"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_memory_empty_key_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/memory", json={"key": "", "value": "Alice"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_memory_excludes_note_keys(app):
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "user_name", "value": "Alice"},
        {"key": "note_20260616_120000", "value": "buy milk"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/memory")
    data = r.json()
    assert len(data) == 1
    assert data[0]["key"] == "user_name"
