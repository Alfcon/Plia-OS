from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_httpx_response(status_code: int, is_success: bool = True):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = is_success
    return resp


@pytest.mark.asyncio
async def test_probe_missing_url_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/probe", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_probe_success():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=_mock_httpx_response(200, True))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/probe", json={"url": "http://example.com"})

    assert r.status_code == 200
    d = r.json()
    assert "url" in d
    assert "elapsed_ms" in d


@pytest.mark.asyncio
async def test_probe_network_error_returns_ok_false():
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(side_effect=httpx.ConnectError("unreachable"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/probe", json={"url": "http://unreachable.invalid"})

    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["error"] is not None


@pytest.mark.asyncio
async def test_probe_history_endpoint():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/probe/history")
    assert r.status_code == 200
    assert "history" in r.json()
    assert isinstance(r.json()["history"], list)


@pytest.mark.asyncio
async def test_probe_stores_in_history():
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=_mock_httpx_response(200, True))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/probe", json={"url": "http://probe-history-test.example"})
            r = await c.get("/api/probe/history")

    history = r.json()["history"]
    assert any("probe-history-test" in (h.get("url") or "") for h in history)


@pytest.mark.asyncio
async def test_probe_method_field():
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=_mock_httpx_response(200, True))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/probe", json={"url": "http://x.example", "method": "HEAD"})

    assert r.status_code == 200
    assert r.json()["method"] == "HEAD"
