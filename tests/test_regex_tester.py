from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_regex_basic_match():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": r"\d+", "text": "abc 123 def 456"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["count"] == 2
    assert d["matches"][0]["match"] == "123"
    assert d["matches"][1]["match"] == "456"


@pytest.mark.asyncio
async def test_regex_no_match():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": r"\d+", "text": "no digits here"})
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["matches"] == []


@pytest.mark.asyncio
async def test_regex_invalid_pattern():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": "[unclosed", "text": "test"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert d["error"] is not None


@pytest.mark.asyncio
async def test_regex_missing_pattern_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": "", "text": "test"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_regex_capture_groups():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": r"(\w+)@(\w+)", "text": "user@example"})
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 1
    assert d["matches"][0]["groups"] == ["user", "example"]


@pytest.mark.asyncio
async def test_regex_case_insensitive_flag():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": "hello", "text": "HELLO world", "flags": "i"})
    assert r.status_code == 200
    assert r.json()["count"] == 1


@pytest.mark.asyncio
async def test_regex_match_positions():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/regex", json={"pattern": "bc", "text": "abcdef"})
    assert r.status_code == 200
    m = r.json()["matches"][0]
    assert m["start"] == 1
    assert m["end"] == 3
