from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── Unit: _fire_cron_job ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fire_plain_message():
    from core.cron_loop import _fire_cron_job
    emitted = []
    with patch("core.cron_loop.events") as mock_events:
        mock_events.emit = AsyncMock(side_effect=lambda t, d: emitted.append(d))
        await _fire_cron_job({"id": 1, "name": "hello", "message": "Good morning"})
    assert emitted[0]["message"] == "[Cron: hello] Good morning"


@pytest.mark.asyncio
async def test_fire_tool_message():
    from core.cron_loop import _fire_cron_job
    emitted = []
    with patch("core.cron_loop.events") as mock_events, \
         patch("core.registry.call_tool_async", new_callable=AsyncMock, return_value="pong") as mock_tool:
        mock_events.emit = AsyncMock(side_effect=lambda t, d: emitted.append(d))
        await _fire_cron_job({"id": 2, "name": "toolcron", "message": "tool:ping"})
    assert "pong" in emitted[0]["message"]


@pytest.mark.asyncio
async def test_fire_workflow_message():
    from core.cron_loop import _fire_cron_job
    emitted = []
    fake_results = [{"result": "done", "error": None}, {"result": "step2 ok", "error": None}]
    with patch("core.cron_loop.events") as mock_events, \
         patch("agents.workflow_store.run_workflow", new_callable=AsyncMock, return_value=fake_results):
        mock_events.emit = AsyncMock(side_effect=lambda t, d: emitted.append(d))
        await _fire_cron_job({"id": 3, "name": "wfcron", "message": "workflow:my_flow"})
    msg = emitted[0]["message"]
    assert "[Cron: wfcron]" in msg
    assert "step2 ok" in msg


@pytest.mark.asyncio
async def test_fire_workflow_not_found():
    from core.cron_loop import _fire_cron_job
    emitted = []
    with patch("core.cron_loop.events") as mock_events, \
         patch("agents.workflow_store.run_workflow", new_callable=AsyncMock, side_effect=KeyError("nope")):
        mock_events.emit = AsyncMock(side_effect=lambda t, d: emitted.append(d))
        await _fire_cron_job({"id": 4, "name": "brokenwf", "message": "workflow:ghost"})
    assert "failed" in emitted[0]["message"].lower()


@pytest.mark.asyncio
async def test_fire_workflow_strips_prefix():
    from core.cron_loop import _fire_cron_job
    emitted = []
    called_with = []
    async def _mock_run(name, **kw):
        called_with.append(name)
        return [{"result": "ok", "error": None}]
    with patch("core.cron_loop.events") as mock_events, \
         patch("agents.workflow_store.run_workflow", side_effect=_mock_run):
        mock_events.emit = AsyncMock(side_effect=lambda t, d: emitted.append(d))
        await _fire_cron_job({"id": 5, "name": "wf", "message": "workflow:  my_flow  "})
    assert called_with[0] == "my_flow"


@pytest.mark.asyncio
async def test_fire_workflow_empty_results():
    from core.cron_loop import _fire_cron_job
    emitted = []
    with patch("core.cron_loop.events") as mock_events, \
         patch("agents.workflow_store.run_workflow", new_callable=AsyncMock, return_value=[]):
        mock_events.emit = AsyncMock(side_effect=lambda t, d: emitted.append(d))
        await _fire_cron_job({"id": 6, "name": "empty", "message": "workflow:x"})
    assert "[Cron: empty]" in emitted[0]["message"]


# ── API: cron CRUD with workflow message ──────────────────────────────────────

@pytest.mark.asyncio
async def test_add_cron_workflow_message():
    from agents.cron_store import get_cron_store
    with patch("agents.cron_store._store", None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/cron", json={
                "name": "test_wf_sched",
                "expr": "0 9 * * *",
                "message": "workflow:my_flow",
            })
    assert r.status_code == 200
    assert r.json()["message"] == "workflow:my_flow"


@pytest.mark.asyncio
async def test_list_cron_includes_next_run():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/cron")
    assert r.status_code == 200
    # May be empty list — just check structure
    for job in r.json():
        assert "next_run" in job
        assert "expr" in job
        assert "message" in job


@pytest.mark.asyncio
async def test_cron_workflow_round_trip():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r_add = await c.post("/api/cron", json={
            "name": "roundtrip_wf",
            "expr": "*/5 * * * *",
            "message": "workflow:daily_report",
        })
        assert r_add.status_code == 200
        r_list = await c.get("/api/cron")
        jobs = r_list.json()
        entry = next((j for j in jobs if j["name"] == "roundtrip_wf"), None)
        assert entry is not None
        assert entry["message"] == "workflow:daily_report"
        r_del = await c.delete("/api/cron/roundtrip_wf")
    assert r_del.status_code == 200
