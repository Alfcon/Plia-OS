from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── agent_routing event enrichment ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_supervisor_keyword_route_emits_enriched_event():
    from core import events
    emitted = []
    async def capture(payload):
        emitted.append(payload)
    events.subscribe(capture)
    try:
        from core.supervisor import _supervisor_node
        state = {
            "messages": [{"role": "user", "content": "search for python tutorials"}],
            "memory_context": "",
            "active_agent": None,
            "search_provider": "duckduckgo",
            "hop_count": 0,
            "tool_results": [],
            "direct_result": "",
        }
        result = await _supervisor_node(state)
        routing_events = [e for e in emitted if e.get("type") == "agent_routing"]
        assert routing_events, "No agent_routing event emitted"
        ev = routing_events[0]
        assert ev["agent"] == "web"
        assert ev["routing_method"] == "keyword"
        assert "query" in ev
        assert "latency_ms" in ev
    finally:
        events._subscribers.remove(capture)


@pytest.mark.asyncio
async def test_supervisor_llm_route_emits_enriched_event():
    from core import events
    emitted = []
    async def capture(payload):
        emitted.append(payload)
    events.subscribe(capture)
    try:
        from core.supervisor import _supervisor_node
        with patch("core.supervisor.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "calendar"}
            state = {
                "messages": [{"role": "user", "content": "something unambiguous calendar related xyzq"}],
                "memory_context": "",
                "active_agent": None,
                "search_provider": "duckduckgo",
                "hop_count": 0,
                "tool_results": [],
                "direct_result": "",
            }
            result = await _supervisor_node(state)
        routing_events = [e for e in emitted if e.get("type") == "agent_routing"]
        assert routing_events
        ev = routing_events[-1]
        assert ev["routing_method"] == "llm"
        assert "latency_ms" in ev
        assert isinstance(ev["latency_ms"], int)
    finally:
        events._subscribers.remove(capture)


@pytest.mark.asyncio
async def test_supervisor_respond_intent_still_emits():
    from core import events
    emitted = []
    async def capture(payload):
        emitted.append(payload)
    events.subscribe(capture)
    try:
        from core.supervisor import _supervisor_node
        with patch("core.supervisor.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "respond"}
            state = {
                "messages": [{"role": "user", "content": "what is 2+2"}],
                "memory_context": "",
                "active_agent": None,
                "search_provider": "duckduckgo",
                "hop_count": 0,
                "tool_results": [],
                "direct_result": "",
            }
            await _supervisor_node(state)
        routing_events = [e for e in emitted if e.get("type") == "agent_routing"]
        assert routing_events
        ev = routing_events[-1]
        assert ev["agent"] == "respond"
    finally:
        events._subscribers.remove(capture)


@pytest.mark.asyncio
async def test_supervisor_direct_tool_emits_event():
    from core import events
    emitted = []
    async def capture(payload):
        emitted.append(payload)
    events.subscribe(capture)
    try:
        from core.supervisor import _supervisor_node
        with patch("core.supervisor.call_tool_async", new_callable=AsyncMock) as mock_tool:
            mock_tool.return_value = "briefing result"
            state = {
                "messages": [{"role": "user", "content": "morning briefing"}],
                "memory_context": "",
                "active_agent": None,
                "search_provider": "duckduckgo",
                "hop_count": 0,
                "tool_results": [],
                "direct_result": "",
            }
            await _supervisor_node(state)
        routing_events = [e for e in emitted if e.get("type") == "agent_routing"]
        assert routing_events
        ev = routing_events[0]
        assert ev["routing_method"] == "direct_tool"
        assert ev["tool"] == "morning_briefing"
    finally:
        events._subscribers.remove(capture)


@pytest.mark.asyncio
async def test_supervisor_query_snippet_in_event():
    from core import events
    emitted = []
    async def capture(payload):
        emitted.append(payload)
    events.subscribe(capture)
    try:
        from core.supervisor import _supervisor_node
        msg = "search for something very specific"
        state = {
            "messages": [{"role": "user", "content": msg}],
            "memory_context": "",
            "active_agent": None,
            "search_provider": "duckduckgo",
            "hop_count": 0,
            "tool_results": [],
            "direct_result": "",
        }
        await _supervisor_node(state)
        routing_events = [e for e in emitted if e.get("type") == "agent_routing"]
        assert routing_events
        assert routing_events[0]["query"] == msg[:120]
    finally:
        events._subscribers.remove(capture)


# ── GET /api/inspector ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inspector_returns_structure():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/inspector")
    assert r.status_code == 200
    data = r.json()
    assert "turns" in data
    assert "count" in data
    assert isinstance(data["turns"], list)


@pytest.mark.asyncio
async def test_inspector_returns_enriched_fields():
    from core.event_log import get_events
    fake_events = [
        {
            "ts": 1700000000.0,
            "event_type": "agent_routing",
            "data": {
                "type": "agent_routing",
                "agent": "web",
                "routing_method": "keyword",
                "query": "search for cats",
                "latency_ms": 0,
            },
        }
    ]
    with patch("dashboard.server.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = fake_events
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/inspector?n=10")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    turn = data["turns"][0]
    assert turn["agent"] == "web"
    assert turn["routing_method"] == "keyword"
    assert turn["query"] == "search for cats"
    assert turn["latency_ms"] == 0


@pytest.mark.asyncio
async def test_inspector_empty():
    with patch("dashboard.server.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = []
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/inspector")
    assert r.status_code == 200
    assert r.json() == {"turns": [], "count": 0}
