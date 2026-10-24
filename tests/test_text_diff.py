from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_diff_identical_texts():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "hello\nworld\n", "b": "hello\nworld\n"})
    assert r.status_code == 200
    d = r.json()
    assert d["added"] == 0
    assert d["removed"] == 0


@pytest.mark.asyncio
async def test_diff_added_lines():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "line1\n", "b": "line1\nnew line\n"})
    assert r.status_code == 200
    d = r.json()
    assert d["added"] == 1
    assert d["removed"] == 0


@pytest.mark.asyncio
async def test_diff_removed_lines():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "line1\nline2\n", "b": "line1\n"})
    assert r.status_code == 200
    d = r.json()
    assert d["removed"] == 1
    assert d["added"] == 0


@pytest.mark.asyncio
async def test_diff_changed_lines():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "foo\n", "b": "bar\n"})
    assert r.status_code == 200
    d = r.json()
    assert d["added"] >= 1
    assert d["removed"] >= 1


@pytest.mark.asyncio
async def test_diff_lines_types():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "old\n", "b": "new\n"})
    assert r.status_code == 200
    types = {l["type"] for l in r.json()["lines"]}
    assert types <= {"add", "remove", "header", "context"}


@pytest.mark.asyncio
async def test_diff_unified_field_is_string():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "x\n", "b": "y\n"})
    assert r.status_code == 200
    assert isinstance(r.json()["unified"], str)


@pytest.mark.asyncio
async def test_diff_empty_strings():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={})
    assert r.status_code == 200
    d = r.json()
    assert d["added"] == 0
    assert d["removed"] == 0
