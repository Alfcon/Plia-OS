from __future__ import annotations

import time
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_timestamp_now():
    before = time.time()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={})
    after = time.time()
    assert r.status_code == 200
    d = r.json()
    assert before <= d["unix"] <= after


@pytest.mark.asyncio
async def test_timestamp_from_unix():
    ts = 1700000000.0
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={"value": ts})
    assert r.status_code == 200
    d = r.json()
    assert d["unix"] == ts
    assert d["unix_ms"] == int(ts * 1000)


@pytest.mark.asyncio
async def test_timestamp_from_iso():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={"value": "2023-11-14T22:13:20Z"})
    assert r.status_code == 200
    d = r.json()
    assert abs(d["unix"] - 1700000000.0) < 2


@pytest.mark.asyncio
async def test_timestamp_response_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={})
    assert r.status_code == 200
    d = r.json()
    for field in ("unix", "unix_ms", "iso_utc", "iso_local", "human_utc", "human_local", "relative"):
        assert field in d, f"missing field: {field}"


@pytest.mark.asyncio
async def test_timestamp_invalid_string_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={"value": "not-a-timestamp"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_timestamp_string_unix():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={"value": "1700000000"})
    assert r.status_code == 200
    assert r.json()["unix"] == 1700000000.0


@pytest.mark.asyncio
async def test_timestamp_relative_field_is_string():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/timestamp", json={})
    assert isinstance(r.json()["relative"], str)
