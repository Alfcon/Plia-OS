from __future__ import annotations

import time
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _reset():
    import dashboard.server as srv
    srv._WORKFLOW_HISTORY.clear()


@pytest.mark.asyncio
async def test_history_empty():
    _reset()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/workflows/history")
    assert r.status_code == 200
    assert r.json()["history"] == []
    _reset()


@pytest.mark.asyncio
async def test_history_recorded_on_run():
    _reset()
    with patch("agents.workflow_store.run_workflow", return_value=[
        {"step": 0, "tool": "get_weather", "params": {}, "note": "", "result": "sunny", "error": None, "duration_ms": 10}
    ]):
        with patch("agents.workflow_store.get_workflow", return_value={"name": "test", "steps": [{"tool": "get_weather", "params": {}}]}):
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                await c.post("/api/workflows/test/run")
                r = await c.get("/api/workflows/history")
    data = r.json()
    assert len(data["history"]) >= 1
    assert data["history"][0]["name"] == "test"
    _reset()


@pytest.mark.asyncio
async def test_history_records_success():
    _reset()
    with patch("agents.workflow_store.run_workflow", return_value=[
        {"step": 0, "tool": "t", "params": {}, "note": "", "result": "ok", "error": None, "duration_ms": 5}
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/workflows/mywf/run")
            r = await c.get("/api/workflows/history")
    assert r.json()["history"][0]["success"] is True
    _reset()


@pytest.mark.asyncio
async def test_history_records_failure():
    _reset()
    with patch("agents.workflow_store.run_workflow", return_value=[
        {"step": 0, "tool": "t", "params": {}, "note": "", "result": "", "error": "tool failed", "duration_ms": 5}
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/workflows/badwf/run")
            r = await c.get("/api/workflows/history")
    h = r.json()["history"][0]
    assert h["success"] is False
    assert "tool failed" in h["errors"]
    _reset()


@pytest.mark.asyncio
async def test_history_has_timestamp():
    _reset()
    import dashboard.server as srv
    srv._WORKFLOW_HISTORY.appendleft({"ts": time.time(), "name": "wf", "steps": 1, "duration_ms": 10, "success": True, "errors": []})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/workflows/history")
    assert r.json()["history"][0]["ts"] > 0
    _reset()


@pytest.mark.asyncio
async def test_history_clear():
    _reset()
    import dashboard.server as srv
    srv._WORKFLOW_HISTORY.appendleft({"ts": time.time(), "name": "x", "steps": 1, "duration_ms": 1, "success": True, "errors": []})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/workflows/history")
    assert r.json()["ok"] is True
    assert len(srv._WORKFLOW_HISTORY) == 0


@pytest.mark.asyncio
async def test_history_n_param():
    _reset()
    import dashboard.server as srv
    for i in range(10):
        srv._WORKFLOW_HISTORY.appendleft({"ts": time.time(), "name": f"wf{i}", "steps": 1, "duration_ms": i, "success": True, "errors": []})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/workflows/history?n=3")
    assert len(r.json()["history"]) == 3
    _reset()
