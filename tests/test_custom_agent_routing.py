# tests/test_custom_agent_routing.py
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_DEFN = {
    "name": "finance",
    "display_name": "Finance Assistant",
    "system_prompt": "You are a finance specialist.",
    "tool_names": ["calculate"],
    "keywords": ["stock", "portfolio"],
    "llm_description": "Use for financial questions",
    "enabled": True,
}


@pytest.fixture()
def agents_file(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield tmp_path / "custom_agents.json"


@pytest.mark.asyncio
async def test_list_empty(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/agents")
    assert r.status_code == 200
    assert r.json()["agents"] == []


@pytest.mark.asyncio
async def test_create_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json=_DEFN)
    assert r.status_code == 201
    d = r.json()
    assert d["name"] == "finance"
    assert d["display_name"] == "Finance Assistant"
    assert d["created_at"] != ""


@pytest.mark.asyncio
async def test_create_duplicate_409(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.post("/api/agents", json=_DEFN)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_invalid_slug_422(agents_file):
    bad = {**_DEFN, "name": "Bad Name!"}
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json=bad)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.get("/api/agents/finance")
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "You are a finance specialist."


@pytest.mark.asyncio
async def test_get_missing_404(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/agents/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.put("/api/agents/finance", json={"display_name": "Finance v2",
                                                      "system_prompt": "Updated.",
                                                      "tool_names": [],
                                                      "keywords": [],
                                                      "llm_description": "",
                                                      "enabled": True})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Finance v2"


@pytest.mark.asyncio
async def test_update_missing_404(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.put("/api/agents/nope", json={"display_name": "x", "system_prompt": "x",
                                                   "tool_names": [], "keywords": [],
                                                   "llm_description": "", "enabled": True})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.delete("/api/agents/finance")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_missing_404(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/agents/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_toggle_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.post("/api/agents/finance/toggle")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "finance"
    assert d["enabled"] is False


@pytest.mark.asyncio
async def test_list_shows_counts(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.get("/api/agents")
    agents = r.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["keyword_count"] == 2
    assert agents[0]["tool_count"] == 1


@pytest.mark.asyncio
async def test_agents_updated_event_fires_on_create(agents_file):
    from core import events
    fired = []
    async def capture(p):
        if p.get("type") == "agents_updated":
            fired.append(p)
    events.subscribe(capture)
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/agents", json=_DEFN)
    finally:
        events.unsubscribe(capture)
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_agents_updated_event_fires_on_delete(agents_file):
    from core import events
    fired = []
    async def capture(p):
        if p.get("type") == "agents_updated":
            fired.append(p)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        events.subscribe(capture)
        try:
            await c.delete("/api/agents/finance")
        finally:
            events.unsubscribe(capture)
    assert len(fired) == 1
