from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_SAMPLE_WF = {
    "description": "test",
    "steps": [
        {"tool": "system_info", "params": {}, "note": "get info"},
        {"tool": "set_reminder", "params": {"message": "hi", "when": "now"}, "note": ""},
    ],
}


@pytest.mark.asyncio
async def test_dryrun_not_found_404():
    with patch("agents.workflow_store.get_workflow", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/missing/dryrun")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_dryrun_returns_dry_run_flag():
    with patch("agents.workflow_store.get_workflow", return_value=_SAMPLE_WF):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/myflow/dryrun")
    assert r.status_code == 200
    data = r.json()
    assert data["dry_run"] is True
    assert data["name"] == "myflow"


@pytest.mark.asyncio
async def test_dryrun_returns_all_steps():
    with patch("agents.workflow_store.get_workflow", return_value=_SAMPLE_WF):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/myflow/dryrun")
    assert len(r.json()["steps"]) == 2


@pytest.mark.asyncio
async def test_dryrun_no_tool_calls():
    called = []
    orig_tool = None

    async def _fake_call(name, params):
        called.append(name)
        return "ok"

    with patch("agents.workflow_store.get_workflow", return_value=_SAMPLE_WF), \
         patch("agents.workflow_store.call_tool_async", side_effect=_fake_call):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/workflows/myflow/dryrun")

    assert called == [], "dry run must not call any tools"


@pytest.mark.asyncio
async def test_dryrun_step_has_dry_run_true():
    with patch("agents.workflow_store.get_workflow", return_value=_SAMPLE_WF):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/myflow/dryrun")
    for step in r.json()["steps"]:
        assert step["dry_run"] is True


@pytest.mark.asyncio
async def test_dryrun_step_result_contains_tool_name():
    with patch("agents.workflow_store.get_workflow", return_value=_SAMPLE_WF):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/myflow/dryrun")
    step0 = r.json()["steps"][0]
    assert "system_info" in step0["result"]


@pytest.mark.asyncio
async def test_dryrun_duration_ms_zero():
    with patch("agents.workflow_store.get_workflow", return_value=_SAMPLE_WF):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/myflow/dryrun")
    for step in r.json()["steps"]:
        assert step["duration_ms"] == 0
