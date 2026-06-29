from __future__ import annotations
import json
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── Unit tests for workflow_store ─────────────────────────────────────────────

def test_save_and_get(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        from agents.workflow_store import save_workflow, get_workflow
        save_workflow("greet", [{"tool": "get_time", "params": {}, "note": ""}], "test wf")
        wf = get_workflow("greet")
    assert wf["name"] == "greet"
    assert wf["description"] == "test wf"
    assert len(wf["steps"]) == 1


def test_list_empty(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        from agents.workflow_store import list_workflows
        assert list_workflows() == []


def test_list_populated(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import save_workflow, list_workflows
        save_workflow("a", [], "")
        save_workflow("b", [], "")
        result = list_workflows()
    assert {w["name"] for w in result} == {"a", "b"}


def test_delete(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import save_workflow, delete_workflow, get_workflow
        save_workflow("todel", [], "")
        assert delete_workflow("todel") is True
        assert get_workflow("todel") is None


def test_delete_nonexistent(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import delete_workflow
        assert delete_workflow("ghost") is False


def test_save_workflow_with_event_trigger(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        from agents.workflow_store import save_workflow, get_workflow
        save_workflow("trig", [], "desc", event_trigger="reminder_fired")
        wf = get_workflow("trig")
    assert wf["event_trigger"] == "reminder_fired"


def test_event_trigger_defaults_none(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        from agents.workflow_store import save_workflow, get_workflow
        save_workflow("plain", [], "")
        wf = get_workflow("plain")
    assert wf["event_trigger"] is None


def test_interpolate_prev(tmp_path):
    from agents.workflow_store import _interpolate
    assert _interpolate("{{prev}}", ["hello"]) == "hello"
    assert _interpolate("{{prev}}", []) == ""


def test_interpolate_step_n(tmp_path):
    from agents.workflow_store import _interpolate
    results = ["first", "second", "third"]
    assert _interpolate("{{step_0}}", results) == "first"
    assert _interpolate("{{step_2}}", results) == "third"
    assert _interpolate("{{step_5}}", results) == "{{step_5}}"


def test_interpolate_non_string():
    from agents.workflow_store import _interpolate
    assert _interpolate(42, ["x"]) == 42
    assert _interpolate(True, ["x"]) is True


@pytest.mark.asyncio
async def test_run_workflow(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import save_workflow, run_workflow
        save_workflow("chain", [
            {"tool": "get_time", "params": {}, "note": "step 0"},
            {"tool": "get_time", "params": {}, "note": "step 1"},
        ], "")
        with patch("agents.workflow_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "12:00"
            results = await run_workflow("chain")
    assert len(results) == 2
    assert results[0]["tool"] == "get_time"
    assert results[0]["result"] == "12:00"
    assert results[1]["result"] == "12:00"
    assert results[0]["error"] is None


@pytest.mark.asyncio
async def test_run_workflow_step_error_stops(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import save_workflow, run_workflow
        save_workflow("err_chain", [
            {"tool": "fail_tool", "params": {}, "note": ""},
            {"tool": "never_called", "params": {}, "note": ""},
        ], "")
        with patch("agents.workflow_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("boom")
            results = await run_workflow("err_chain")
    assert len(results) == 1
    assert results[0]["error"] == "boom"


@pytest.mark.asyncio
async def test_run_workflow_prev_interpolation(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import save_workflow, run_workflow
        save_workflow("interp", [
            {"tool": "echo", "params": {}, "note": ""},
            {"tool": "echo", "params": {"msg": "{{prev}}"}, "note": ""},
        ], "")
        calls = []
        async def fake_call(name, params):
            calls.append((name, params))
            return "pong"
        with patch("agents.workflow_store.call_tool_async", side_effect=fake_call):
            await run_workflow("interp")
    assert calls[1][1]["msg"] == "pong"


@pytest.mark.asyncio
async def test_run_missing_workflow(tmp_path):
    p = tmp_path / "wf.json"
    with patch("agents.workflow_store._workflows_path", return_value=p):
        from agents.workflow_store import run_workflow
        with pytest.raises(KeyError):
            await run_workflow("ghost")


# ── API endpoint tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_list_empty(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/workflows")
    assert r.status_code == 200
    assert r.json()["workflows"] == []


@pytest.mark.asyncio
async def test_api_save_and_list(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows", json={"name": "mywf", "steps": [], "description": "d"})
            assert r.status_code == 200
            r2 = await c.get("/api/workflows")
    assert any(w["name"] == "mywf" for w in r2.json()["workflows"])


@pytest.mark.asyncio
async def test_api_save_missing_name():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/workflows", json={"steps": []})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_delete(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/workflows", json={"name": "todel", "steps": [], "description": ""})
            r = await c.delete("/api/workflows/todel")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_api_delete_not_found(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/workflows/ghost")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_run(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        with patch("agents.workflow_store.call_tool_async", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "done"
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                await c.post("/api/workflows", json={
                    "name": "runme", "steps": [{"tool": "get_time", "params": {}, "note": ""}], "description": ""
                })
                r = await c.post("/api/workflows/runme/run")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "runme"
    assert data["steps"][0]["result"] == "done"


@pytest.mark.asyncio
async def test_api_run_not_found(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/workflows/ghost/run")
    assert r.status_code == 404
