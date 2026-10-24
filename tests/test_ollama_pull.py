from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_pull_no_model_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/ollama/pull", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pull_no_ollama_url_503():
    with patch("dashboard.server.get_config") as m:
        cfg = m.return_value
        cfg.ollama_url = ""
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/ollama/pull", json={"model": "llama3"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_pull_streams_sse():
    lines = ['{"status":"pulling manifest"}', '{"status":"done"}']

    async def _fake_aiter_lines():
        for line in lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.aiter_lines = _fake_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("dashboard.server.get_config") as mcfg, \
         patch("httpx.AsyncClient", return_value=mock_client):
        mcfg.return_value.ollama_url = "http://localhost:11434"
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/ollama/pull", json={"model": "llama3"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_pull_response_contains_data_lines():
    lines = ['{"status":"downloading","completed":100,"total":1000}']

    async def _fake_aiter_lines():
        for line in lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.aiter_lines = _fake_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("dashboard.server.get_config") as mcfg, \
         patch("httpx.AsyncClient", return_value=mock_client):
        mcfg.return_value.ollama_url = "http://localhost:11434"
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/ollama/pull", json={"model": "llama3"})
    assert b"data:" in r.content


@pytest.mark.asyncio
async def test_pull_ends_with_done():
    async def _fake_aiter_lines():
        return
        yield  # make it an async generator

    mock_resp = MagicMock()
    mock_resp.aiter_lines = _fake_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("dashboard.server.get_config") as mcfg, \
         patch("httpx.AsyncClient", return_value=mock_client):
        mcfg.return_value.ollama_url = "http://localhost:11434"
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/ollama/pull", json={"model": "llama3"})
    assert b'"done"' in r.content
