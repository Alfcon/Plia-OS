from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _ollama_lines(*tokens, done_token=""):
    """Ollama streaming format lines (what the endpoint reads from Ollama)."""
    lines = []
    for tok in tokens:
        lines.append(json.dumps({"message": {"role": "assistant", "content": tok}, "done": False}))
    lines.append(json.dumps({"message": {"role": "assistant", "content": done_token}, "done": True}))
    return lines


class _MockStream:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


def _mock_http_client(lines):
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=_MockStream(lines))
    return mock_client


@pytest.mark.asyncio
async def test_stream_missing_prompt_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/chat/stream", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stream_content_type_sse():
    with patch("httpx.AsyncClient", return_value=_mock_http_client(_ollama_lines("Hi"))):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={"prompt": "hi"})
    assert "text/event-stream" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_stream_tokens_forwarded():
    with patch("httpx.AsyncClient", return_value=_mock_http_client(_ollama_lines("Hello", " world"))):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={"prompt": "hi"})
    body = r.text
    assert "Hello" in body
    assert "world" in body


@pytest.mark.asyncio
async def test_stream_done_sentinel_present():
    with patch("httpx.AsyncClient", return_value=_mock_http_client(_ollama_lines("x"))):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={"prompt": "test"})
    assert "[DONE]" in r.text


@pytest.mark.asyncio
async def test_stream_connection_error_yields_error_event():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(side_effect=Exception("connection refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={"prompt": "test"})
    assert r.status_code == 200
    assert "error" in r.text


@pytest.mark.asyncio
async def test_stream_messages_body():
    with patch("httpx.AsyncClient", return_value=_mock_http_client(_ollama_lines("ok"))):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}]
            })
    assert r.status_code == 200
    assert "ok" in r.text


@pytest.mark.asyncio
async def test_stream_skips_empty_tokens():
    lines = [
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": "real"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}),
    ]
    with patch("httpx.AsyncClient", return_value=_mock_http_client(lines)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={"prompt": "test"})
    body = r.text
    # Only "real" token should appear; empty tokens filtered
    assert "real" in body


@pytest.mark.asyncio
async def test_stream_invalid_json_lines_ignored():
    lines = ["not-json", json.dumps({"message": {"role": "assistant", "content": "good"}, "done": True})]
    with patch("httpx.AsyncClient", return_value=_mock_http_client(lines)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/chat/stream", json={"prompt": "test"})
    assert r.status_code == 200
    assert "good" in r.text
