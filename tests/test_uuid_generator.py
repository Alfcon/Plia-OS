from __future__ import annotations

import re
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[14][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_v4_generates_uuids():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 4, "count": 3})
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 3
    assert len(d["uuids"]) == 3


@pytest.mark.asyncio
async def test_v4_format():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 4, "count": 1})
    uid = r.json()["uuids"][0]
    assert UUID_RE.match(uid), f"Not valid UUID4: {uid}"


@pytest.mark.asyncio
async def test_v1_generates():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 1, "count": 2})
    assert r.status_code == 200
    assert r.json()["version"] == 1


@pytest.mark.asyncio
async def test_upper_flag():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 4, "count": 1, "upper": True})
    uid = r.json()["uuids"][0]
    assert uid == uid.upper()


@pytest.mark.asyncio
async def test_count_capped_at_50():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 4, "count": 999})
    assert len(r.json()["uuids"]) == 50


@pytest.mark.asyncio
async def test_invalid_version_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 3, "count": 1})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unique_uuids():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/uuid", json={"version": 4, "count": 10})
    uuids = r.json()["uuids"]
    assert len(set(uuids)) == 10
