from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_token_count_empty():
    with patch("agents.chat_history.get_recent", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/tokens")
    assert r.status_code == 200
    data = r.json()
    assert data["message_count"] == 0
    assert data["estimated_tokens"] == 0


@pytest.mark.asyncio
async def test_token_count_calculates():
    messages = [
        {"role": "user", "content": "Hello world"},
        {"role": "assistant", "content": "Hi there"},
    ]
    with patch("agents.chat_history.get_recent", return_value=messages):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/tokens")
    data = r.json()
    assert data["message_count"] == 2
    total_chars = len("Hello world") + len("Hi there")
    assert data["total_chars"] == total_chars
    assert data["estimated_tokens"] == round(total_chars / 4)


@pytest.mark.asyncio
async def test_token_count_has_model_note():
    with patch("agents.chat_history.get_recent", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/chat/tokens")
    assert "model_context_note" in r.json()


@pytest.mark.asyncio
async def test_token_count_n_param():
    with patch("agents.chat_history.get_recent") as mock_get:
        mock_get.return_value = []
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.get("/api/chat/tokens?n=50")
        mock_get.assert_called_once_with(50)
