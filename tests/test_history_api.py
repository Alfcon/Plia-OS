import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock, AsyncMock
from core.main import create_app
from core import events


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_get_history_returns_messages(app):
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    with patch("agents.chat_history.get_recent", return_value=messages):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/history")
    assert r.status_code == 200
    assert r.json() == messages


@pytest.mark.asyncio
async def test_get_history_empty(app):
    with patch("agents.chat_history.get_recent", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/history")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_history_passes_n_param(app):
    with patch("agents.chat_history.get_recent", return_value=[]) as mock_get:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/api/history?n=25")
    mock_get.assert_called_once_with(25)


@pytest.mark.asyncio
async def test_delete_history_clears_and_emits(app):
    emitted = []

    async def capture(payload):
        emitted.append(payload)

    events.subscribe(capture)
    try:
        mock_store = MagicMock()
        with patch("agents.chat_history.clear") as mock_clear, \
             patch("agents.memory_store.get_memory_store", return_value=mock_store):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.delete("/api/history")
        assert r.status_code == 200
        assert r.json()["status"] == "cleared"
        mock_clear.assert_called_once()
        mock_store.clear_history.assert_called_once()
        assert any(e.get("type") == "clear_history" for e in emitted)
    finally:
        events.unsubscribe(capture)


@pytest.mark.asyncio
async def test_delete_history_returns_cleared(app):
    mock_store = MagicMock()
    with patch("agents.chat_history.clear"), \
         patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/history")
    assert r.json() == {"status": "cleared"}
