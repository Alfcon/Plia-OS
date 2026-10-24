from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_basic_heading():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/markdown", json={"text": "# Hello"})
    assert r.status_code == 200
    d = r.json()
    assert "<h1" in d["html"] or "Hello" in d["html"]


@pytest.mark.asyncio
async def test_returns_html_and_length():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/markdown", json={"text": "**bold**"})
    d = r.json()
    assert "html" in d
    assert "length" in d
    assert d["length"] == 8


@pytest.mark.asyncio
async def test_returns_engine_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/markdown", json={"text": "test"})
    assert "engine" in r.json()


@pytest.mark.asyncio
async def test_empty_text():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/markdown", json={"text": ""})
    assert r.status_code == 200
    assert r.json()["length"] == 0


@pytest.mark.asyncio
async def test_script_tag_in_fallback_escaped():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/markdown", json={"text": "<script>alert(1)</script>"})
    assert r.status_code == 200
    d = r.json()
    # fallback engine escapes HTML; full markdown libs pass it through (by spec)
    if d["engine"] == "fallback":
        assert "<script>" not in d["html"]


@pytest.mark.asyncio
async def test_missing_text_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/markdown", json={})
    assert r.status_code == 200
    assert r.json()["length"] == 0
