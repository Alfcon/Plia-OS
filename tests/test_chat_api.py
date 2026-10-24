import pytest
import respx
import httpx
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


def _llm_respond(text):
    return httpx.Response(200, json={
        "message": {"role": "assistant", "content": text, "tool_calls": None}
    })


@pytest.mark.asyncio
@respx.mock
async def test_chat_returns_response(app):
    respx.post("http://localhost:11434/api/chat").mock(side_effect=[
        _llm_respond("respond"),
        _llm_respond("Hello there!"),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/chat", json={"text": "hi"})
    assert r.status_code == 200
    assert r.json()["response"] == "Hello there!"


@pytest.mark.asyncio
async def test_chat_empty_text_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/chat", json={"text": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_missing_text_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/chat", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
@respx.mock
async def test_chat_broadcasts_transcript_event(app):
    broadcast_calls = []

    async def fake_broadcast(payload):
        broadcast_calls.append(payload)

    respx.post("http://localhost:11434/api/chat").mock(side_effect=[
        _llm_respond("respond"),
        _llm_respond("Sure thing!"),
    ])
    with patch("dashboard.server._broadcast", side_effect=fake_broadcast):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/api/chat", json={"text": "do something"})
    assert any(
        e.get("type") == "transcript" and e.get("role") == "assistant" and "Sure thing!" in e.get("text", "")
        for e in broadcast_calls
    )


@pytest.mark.asyncio
async def test_chat_includes_recent_history(app):
    from unittest.mock import AsyncMock
    captured_messages = []

    async def mock_run_turn(messages):
        captured_messages.extend(messages)
        return "ok", []

    mock_history = [
        {"role": "user", "content": "earlier message", "ts": "2026-01-01T00:00:00"},
    ]
    with patch("agents.chat_history.get_recent", return_value=mock_history):
        with patch("core.supervisor.run_turn", side_effect=mock_run_turn):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                await ac.post("/api/chat", json={"text": "new message"})

    assert any(m["content"] == "earlier message" for m in captured_messages)
    assert captured_messages[-1]["content"] == "new message"
