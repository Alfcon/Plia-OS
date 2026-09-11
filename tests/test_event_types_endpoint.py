from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_event_types_200():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/events/types")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_event_types_returns_list():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/events/types")
    d = r.json()
    assert "types" in d
    assert isinstance(d["types"], list)


@pytest.mark.asyncio
async def test_event_types_reflects_patched_types():
    with patch("core.event_log.get_event_types", return_value=["status", "transcript", "reminder_fired"]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/events/types")
    assert r.status_code == 200
    assert set(r.json()["types"]) == {"status", "transcript", "reminder_fired"}


@pytest.mark.asyncio
async def test_event_types_distinct_only():
    with patch("core.event_log.get_event_types", return_value=["status", "transcript"]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/events/types")
    types = r.json()["types"]
    assert len(types) == len(set(types))


@pytest.mark.asyncio
async def test_event_types_not_captured_by_events_route():
    # /api/events/types must not be confused with /api/events
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r1 = await c.get("/api/events/types")
        r2 = await c.get("/api/events")
    # Both should respond (not 404/405)
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Different response shapes
    assert "types" in r1.json()
    assert "events" in r2.json()


@pytest.mark.asyncio
async def test_events_route_still_returns_types_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/events")
    assert "types" in r.json()
