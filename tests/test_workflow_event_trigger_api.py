from __future__ import annotations
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


@pytest.fixture()
def agent_path(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "agents.json"):
        yield


@pytest.mark.asyncio
async def test_workflow_event_trigger_saved(wf_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/workflows", json={
            "name": "trig-wf", "steps": [], "description": "d",
            "event_trigger": "reminder_fired",
        })
        assert r.status_code == 200
        r2 = await c.get("/api/workflows")
    match = next(w for w in r2.json()["workflows"] if w["name"] == "trig-wf")
    assert match["event_trigger"] == "reminder_fired"


@pytest.mark.asyncio
async def test_workflow_event_trigger_defaults_none(wf_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/workflows", json={"name": "plain", "steps": [], "description": ""})
        r2 = await c.get("/api/workflows")
    match = next(w for w in r2.json()["workflows"] if w["name"] == "plain")
    assert match["event_trigger"] is None


@pytest.mark.asyncio
async def test_agent_workflow_name_create(agent_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json={
            "name": "briefer",
            "display_name": "Briefer",
            "system_prompt": "You summarize.",
            "tool_names": [],
            "keywords": [],
            "llm_description": "",
            "workflow_name": "daily-brief",
        })
    assert r.status_code == 201
    assert r.json()["workflow_name"] == "daily-brief"


@pytest.mark.asyncio
async def test_agent_workflow_name_update(agent_path):
    base = {
        "name": "briefer", "display_name": "Briefer",
        "system_prompt": "You summarize.", "tool_names": [],
        "keywords": [], "llm_description": "",
    }
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=base)
        r = await c.put("/api/agents/briefer", json={**base, "workflow_name": "new-wf"})
    assert r.status_code == 200
    assert r.json()["workflow_name"] == "new-wf"


@pytest.mark.asyncio
async def test_agent_workflow_name_defaults_none(agent_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json={
            "name": "plain", "display_name": "Plain",
            "system_prompt": "...", "tool_names": [], "keywords": [], "llm_description": "",
        })
    assert r.json()["workflow_name"] is None
