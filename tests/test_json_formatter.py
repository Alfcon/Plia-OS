from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_format_valid_json():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/format", json={"json": '{"a":1,"b":[1,2]}'})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert '"a"' in d["result"]
    assert d["keys"] >= 2


@pytest.mark.asyncio
async def test_format_invalid_json():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/format", json={"json": "{bad json}"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["result"] is None
    assert "line" in d


@pytest.mark.asyncio
async def test_format_respects_indent():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/format", json={"json": '{"x":1}', "indent": 4})
    assert r.status_code == 200
    assert "    " in r.json()["result"]


@pytest.mark.asyncio
async def test_minify_valid_json():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/minify", json={"json": '{\n  "a": 1\n}'})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert " " not in d["result"]
    assert d["saved"] > 0


@pytest.mark.asyncio
async def test_minify_invalid_json():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/minify", json={"json": "[1,2,"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["result"] is None


@pytest.mark.asyncio
async def test_format_empty_string():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/format", json={"json": ""})
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_format_counts_nested_keys():
    payload = '{"a":{"b":{"c":1}}}'
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/json/format", json={"json": payload})
    assert r.status_code == 200
    assert r.json()["keys"] == 3
