from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_full_url_parse():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={"url": "https://example.com/path?foo=bar&baz=qux#section"})
    assert r.status_code == 200
    d = r.json()
    assert d["scheme"] == "https"
    assert d["host"] == "example.com"
    assert d["path"] == "/path"
    assert d["fragment"] == "section"


@pytest.mark.asyncio
async def test_query_params_parsed():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={"url": "https://example.com/?foo=bar&baz=qux"})
    d = r.json()
    assert d["params"]["foo"] == "bar"
    assert d["params"]["baz"] == "qux"


@pytest.mark.asyncio
async def test_port_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={"url": "http://localhost:8080/api"})
    d = r.json()
    assert d["port"] == 8080
    assert d["host"] == "localhost"


@pytest.mark.asyncio
async def test_origin_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={"url": "https://example.com/path"})
    assert r.json()["origin"] == "https://example.com"


@pytest.mark.asyncio
async def test_auto_scheme_added():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={"url": "example.com/path"})
    assert r.status_code == 200
    assert r.json()["scheme"] == "https"


@pytest.mark.asyncio
async def test_missing_url_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_username_password():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/url/parse", json={"url": "ftp://user:pass@ftp.example.com/file"})
    d = r.json()
    assert d["username"] == "user"
    assert d["password"] == "pass"
