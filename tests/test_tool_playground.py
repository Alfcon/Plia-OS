from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── GET /api/tools ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tools_returns_list():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)


@pytest.mark.asyncio
async def test_list_tools_includes_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools")
    tools = r.json()["tools"]
    assert len(tools) > 0
    t = tools[0]
    assert "name" in t
    assert "description" in t
    assert "parameters" in t
    assert "module" in t
    assert "disabled" in t


@pytest.mark.asyncio
async def test_list_tools_sorted():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools")
    names = [t["name"] for t in r.json()["tools"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_tools_parameters_schema():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools")
    for tool in r.json()["tools"]:
        params = tool["parameters"]
        assert "type" in params
        assert params["type"] == "object"
        assert "properties" in params


@pytest.mark.asyncio
async def test_disabled_tool_flagged():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/tools")
    for tool in r.json()["tools"]:
        assert isinstance(tool["disabled"], bool)


# ── POST /api/tools/{name}/run ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_tool_ok():
    with patch("dashboard.server.call_tool_async", new_callable=AsyncMock, return_value="pong") as mock_call:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/ping/run", json={"params": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["result"] == "pong"


@pytest.mark.asyncio
async def test_run_tool_not_found():
    with patch("dashboard.server.call_tool_async", side_effect=KeyError("Unknown tool: 'nope'")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/nope/run", json={"params": {}})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_run_tool_bad_params():
    with patch("dashboard.server.call_tool_async", side_effect=TypeError("unexpected keyword argument")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/some_tool/run", json={"params": {"bad": "arg"}})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_run_tool_runtime_error_returns_ok_false():
    with patch("dashboard.server.call_tool_async", side_effect=RuntimeError("tool exploded")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/boom/run", json={"params": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "tool exploded" in data["error"]


@pytest.mark.asyncio
async def test_run_tool_none_result():
    with patch("dashboard.server.call_tool_async", new_callable=AsyncMock, return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/silent/run", json={"params": {}})
    assert r.status_code == 200
    assert r.json()["result"] == ""


@pytest.mark.asyncio
async def test_run_tool_with_params():
    with patch("dashboard.server.call_tool_async", new_callable=AsyncMock, return_value="42") as mock_call:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/add/run", json={"params": {"a": 1, "b": 2}})
    mock_call.assert_called_once_with("add", {"a": 1, "b": 2})
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_run_tool_missing_params_key():
    with patch("dashboard.server.call_tool_async", new_callable=AsyncMock, return_value="ok"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/tools/t/run", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is True
