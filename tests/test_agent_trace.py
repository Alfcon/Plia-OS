from __future__ import annotations

import time
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset():
    import dashboard.server as srv
    srv._TURN_TRACES.clear()


@pytest.mark.asyncio
async def test_trace_empty():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/trace/recent")
    assert r.status_code == 200
    assert r.json()["traces"] == []
    _reset()


@pytest.mark.asyncio
async def test_trace_populated_by_routing_event():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({
        "type": "agent_routing",
        "agent": "memory",
        "routing_method": "keyword",
        "latency_ms": 5,
        "query": "remember my name",
    })
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/trace/recent")
    traces = r.json()["traces"]
    assert len(traces) == 1
    assert traces[0]["agent"] == "memory"
    assert traces[0]["routing_method"] == "keyword"
    assert traces[0]["latency_ms"] == 5
    assert "remember" in traces[0]["query"]
    _reset()


@pytest.mark.asyncio
async def test_trace_has_timestamp():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "web", "latency_ms": 100, "routing_method": "llm", "query": ""})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/trace/recent")
    t = r.json()["traces"][0]
    assert "ts" in t
    assert t["ts"] > 0
    _reset()


@pytest.mark.asyncio
async def test_trace_ignores_non_routing_events():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "transcript", "agent": "web", "latency_ms": 50})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/trace/recent")
    assert r.json()["traces"] == []
    _reset()


@pytest.mark.asyncio
async def test_trace_n_param():
    _reset()
    import dashboard.server as srv
    for i in range(10):
        srv._on_agent_routing({"type": "agent_routing", "agent": f"agent{i}", "latency_ms": i*10, "routing_method": "llm", "query": ""})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/trace/recent?n=4")
    assert len(r.json()["traces"]) == 4
    _reset()


@pytest.mark.asyncio
async def test_trace_clear():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "code", "latency_ms": 200, "routing_method": "llm", "query": "run code"})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/trace/recent")
    assert r.json()["ok"] is True
    assert len(srv._TURN_TRACES) == 0


@pytest.mark.asyncio
async def test_trace_most_recent_first():
    _reset()
    import dashboard.server as srv
    srv._on_agent_routing({"type": "agent_routing", "agent": "first", "latency_ms": 10, "routing_method": "keyword", "query": "first"})
    srv._on_agent_routing({"type": "agent_routing", "agent": "second", "latency_ms": 20, "routing_method": "llm", "query": "second"})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/trace/recent")
    traces = r.json()["traces"]
    assert traces[0]["agent"] == "second"
    _reset()
