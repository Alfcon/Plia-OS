from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset():
    import dashboard.server as srv
    srv._TOOL_STATS.clear()


@pytest.mark.asyncio
async def test_stats_empty():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools/stats")
    assert r.status_code == 200
    assert r.json()["stats"] == []
    _reset()


@pytest.mark.asyncio
async def test_stats_populated_by_event():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "memory", "latency_ms": 120, "routing_method": "keyword", "query": "test"})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools/stats")
    data = r.json()
    assert len(data["stats"]) == 1
    assert data["stats"][0]["agent"] == "memory"
    assert data["stats"][0]["calls"] == 1
    _reset()


@pytest.mark.asyncio
async def test_stats_avg_latency():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "web", "latency_ms": 100, "routing_method": "llm", "query": ""})
    srv._on_agent_routing({"type": "agent_routing", "agent": "web", "latency_ms": 200, "routing_method": "llm", "query": ""})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools/stats")
    stat = r.json()["stats"][0]
    assert stat["calls"] == 2
    assert stat["avg_latency_ms"] == 150
    _reset()


@pytest.mark.asyncio
async def test_stats_ignores_non_routing_events():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "transcript", "agent": "web", "latency_ms": 100})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools/stats")
    assert r.json()["stats"] == []
    _reset()


@pytest.mark.asyncio
async def test_stats_reset():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "code", "latency_ms": 50, "routing_method": "keyword", "query": ""})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/tools/stats/reset")
        assert r.json()["ok"] is True
        r2 = await c.get("/api/tools/stats")
    assert r2.json()["stats"] == []


@pytest.mark.asyncio
async def test_stats_sorted_by_calls():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "memory", "latency_ms": 10, "routing_method": "keyword", "query": ""})
    for _ in range(3):
        srv._on_agent_routing({"type": "agent_routing", "agent": "respond", "latency_ms": 10, "routing_method": "llm", "query": ""})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools/stats")
    stats = r.json()["stats"]
    assert stats[0]["agent"] == "respond"
    assert stats[0]["calls"] == 3
    _reset()
