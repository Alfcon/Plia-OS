from __future__ import annotations

import time
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_uptime_returns_200():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/uptime")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_uptime_has_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/uptime")
    data = r.json()
    assert "uptime_seconds" in data
    assert "human" in data
    assert "started_at" in data


@pytest.mark.asyncio
async def test_uptime_seconds_positive():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/uptime")
    assert r.json()["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_uptime_started_at_in_past():
    now = time.time()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/uptime")
    assert r.json()["started_at"] <= now


@pytest.mark.asyncio
async def test_uptime_human_nonempty():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/uptime")
    assert len(r.json()["human"]) > 0


@pytest.mark.asyncio
async def test_uptime_human_format():
    import dashboard.server as srv
    import re
    original = srv._SERVER_START
    try:
        srv._SERVER_START = time.time() - 3661  # 1h 1m 1s ago
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/uptime")
        human = r.json()["human"]
        assert "h" in human and "m" in human
    finally:
        srv._SERVER_START = original
