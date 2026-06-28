from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── GET /api/modules ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_modules_returns_list():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/modules")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_list_modules_fields():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/modules")
    modules = r.json()
    assert len(modules) > 0
    m = modules[0]
    assert "name" in m
    assert "tools" in m
    assert "tool_count" in m
    assert "enabled" in m
    assert "on_disk" in m
    assert "loaded" in m


@pytest.mark.asyncio
async def test_list_modules_sorted():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/modules")
    names = [m["name"] for m in r.json()]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_modules_tool_count_matches_tools():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/modules")
    for m in r.json():
        assert m["tool_count"] == len(m["tools"])


@pytest.mark.asyncio
async def test_list_modules_enabled_by_default():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/modules")
    enabled = [m for m in r.json() if m["enabled"]]
    assert len(enabled) > 0


@pytest.mark.asyncio
async def test_list_modules_includes_disk_files(tmp_path):
    fake_mod = tmp_path / "my_custom.py"
    fake_mod.write_text("# no tools\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/modules")
    names = [m["name"] for m in r.json()]
    assert "my_custom" in names


@pytest.mark.asyncio
async def test_list_modules_disk_only_not_loaded(tmp_path):
    fake_mod = tmp_path / "unloaded.py"
    fake_mod.write_text("# no tools\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/modules")
    entry = next((m for m in r.json() if m["name"] == "unloaded"), None)
    assert entry is not None
    assert entry["loaded"] is False
    assert entry["tool_count"] == 0


# ── POST /api/modules/{name}/disable and /enable ─────────────────────────────

@pytest.mark.asyncio
async def test_disable_module():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/web_tools/disable")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_enable_module():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/modules/web_tools/disable")
        r = await c.post("/api/modules/web_tools/enable")
    assert r.status_code == 200
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_disable_reflects_in_list(tmp_path):
    fake = tmp_path / "web_tools.py"
    fake.write_text("# stub\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/modules/web_tools/disable")
            r = await c.get("/api/modules")
    entry = next((m for m in r.json() if m["name"] == "web_tools"), None)
    assert entry is not None
    assert entry["enabled"] is False


@pytest.mark.asyncio
async def test_enable_reflects_in_list(tmp_path):
    fake = tmp_path / "web_tools.py"
    fake.write_text("# stub\n")
    with patch("dashboard.server._MODULES_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/modules/web_tools/disable")
            await c.post("/api/modules/web_tools/enable")
            r = await c.get("/api/modules")
    entry = next((m for m in r.json() if m["name"] == "web_tools"), None)
    assert entry is not None
    assert entry["enabled"] is True


# ── POST /api/modules/reload ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reload_modules_ok():
    with patch("dashboard.server.load_modules"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/modules/reload")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "modules" in data
    assert "tools" in data


@pytest.mark.asyncio
async def test_reload_clears_user_tools():
    from core.registry import _tools
    from core.registry import tool as _tool

    @_tool("test tool for reload")
    def _fake_reload_tool() -> str:
        return "x"

    assert "_fake_reload_tool" in _tools

    with patch("dashboard.server.load_modules"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/modules/reload")

    assert "_fake_reload_tool" not in _tools


@pytest.mark.asyncio
async def test_reload_preserves_mcp_tools():
    from core.registry import _tools, register_tool

    register_tool(
        name="_fake_mcp_tool",
        fn=lambda: None,
        description="mcp tool",
        parameters={"type": "object", "properties": {}, "required": []},
        module="mcp:test",
    )

    with patch("dashboard.server.load_modules"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/modules/reload")

    assert "_fake_mcp_tool" in _tools
    del _tools["_fake_mcp_tool"]
