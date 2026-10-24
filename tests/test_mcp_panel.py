import json
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.mcp_client as mcp_mod
from core.mcp_client import (
    _MCPServer,
    disable_mcp_server,
    get_mcp_status,
    restart_mcp_servers,
)


@pytest.fixture(autouse=True)
def reset_mcp_state():
    mcp_mod._servers.clear()
    mcp_mod._disabled_servers.clear()
    mcp_mod._initialized = False
    mcp_mod._exit_stack = AsyncExitStack()
    mcp_mod._restart_lock = None
    yield
    mcp_mod._servers.clear()
    mcp_mod._disabled_servers.clear()
    mcp_mod._initialized = False
    mcp_mod._exit_stack = AsyncExitStack()
    mcp_mod._restart_lock = None


# ---------------------------------------------------------------------------
# get_mcp_status
# ---------------------------------------------------------------------------

def test_get_mcp_status_no_config(tmp_path):
    with patch.object(mcp_mod, "_MCP_CONFIG", tmp_path / "missing.json"):
        assert get_mcp_status() == []


def test_get_mcp_status_invalid_config(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text("not json")
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        assert get_mcp_status() == []


def test_get_mcp_status_failed_server(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    # fs not in _servers, not in _disabled_servers → failed
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        result = get_mcp_status()
    assert len(result) == 1
    assert result[0]["name"] == "fs"
    assert result[0]["status"] == "failed"
    assert result[0]["tools"] == []
    assert result[0]["uptime_seconds"] is None


def test_get_mcp_status_connected_server(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    srv = _MCPServer(session=MagicMock())
    srv.tools = ["fs__read", "fs__write"]
    mcp_mod._servers["fs"] = srv
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        result = get_mcp_status()
    assert result[0]["status"] == "connected"
    assert result[0]["tools"] == ["fs__read", "fs__write"]
    assert result[0]["uptime_seconds"] is not None
    assert result[0]["uptime_seconds"] >= 0


def test_get_mcp_status_disabled_server(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    srv = _MCPServer(session=MagicMock())
    srv.healthy = False
    mcp_mod._servers["fs"] = srv
    mcp_mod._disabled_servers.add("fs")
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        result = get_mcp_status()
    assert result[0]["status"] == "disabled"


# ---------------------------------------------------------------------------
# disable_mcp_server
# ---------------------------------------------------------------------------

def test_disable_unknown_server_returns_false(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        assert disable_mcp_server("unknown") is False


def test_disable_server_no_config_returns_false(tmp_path):
    with patch.object(mcp_mod, "_MCP_CONFIG", tmp_path / "missing.json"):
        assert disable_mcp_server("fs") is False


def test_disable_known_server(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    srv = _MCPServer(session=MagicMock())
    mcp_mod._servers["fs"] = srv
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        result = disable_mcp_server("fs")
    assert result is True
    assert "fs" in mcp_mod._disabled_servers
    assert srv.healthy is False


def test_disable_server_not_in_servers_still_adds_to_disabled(tmp_path):
    # Server that failed to start — not in _servers but config knows it
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        result = disable_mcp_server("fs")
    assert result is True
    assert "fs" in mcp_mod._disabled_servers


# ---------------------------------------------------------------------------
# restart_mcp_servers
# ---------------------------------------------------------------------------

async def test_restart_resets_state_and_calls_load():
    srv = _MCPServer(session=MagicMock())
    mcp_mod._servers["fs"] = srv
    # Note: no entry in _disabled_servers here — tests server-map reset only.
    mcp_mod._initialized = True

    with patch("core.mcp_client.load_mcp_servers", new_callable=AsyncMock) as mock_load:
        await restart_mcp_servers()

    assert mcp_mod._servers == {}
    assert mcp_mod._disabled_servers == set()
    assert mcp_mod._initialized is False
    mock_load.assert_called_once()


# ---------------------------------------------------------------------------
# Bug 3 — restart must clear MCP tools from registry so re-registration works
# ---------------------------------------------------------------------------

async def test_restart_clears_mcp_tools_from_registry():
    """After restart, stale MCP tools are removed so re-registration succeeds."""
    from core.registry import _tools, clear_tools, register_tool
    clear_tools()

    # Simulate tools that were registered during a previous load
    register_tool(
        name="fs__read",
        fn=lambda: None,
        description="read",
        parameters={},
        module="mcp:fs",
    )
    assert "fs__read" in _tools

    mcp_mod._initialized = True

    with patch("core.mcp_client.load_mcp_servers", new_callable=AsyncMock):
        await restart_mcp_servers()

    assert "fs__read" not in _tools


# ---------------------------------------------------------------------------
# Bug 6 — for-loop guard when config file contains JSON null
# ---------------------------------------------------------------------------

def test_get_mcp_status_null_config(tmp_path):
    """get_mcp_status returns [] if config is JSON null (not a list)."""
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text("null")
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        assert get_mcp_status() == []


def test_disable_mcp_server_null_config(tmp_path):
    """disable_mcp_server returns False if config is JSON null (not a list)."""
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text("null")
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        assert disable_mcp_server("fs") is False


# ---------------------------------------------------------------------------
# Bug 7 — restart preserves user-disabled server state
# ---------------------------------------------------------------------------

async def test_restart_preserves_user_disabled_servers():
    """Servers in _disabled_servers before restart must still be disabled afterward."""
    mcp_mod._disabled_servers.add("user-db")
    mcp_mod._initialized = True

    with patch("core.mcp_client.load_mcp_servers", new_callable=AsyncMock):
        await restart_mcp_servers()

    assert "user-db" in mcp_mod._disabled_servers


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

from httpx import AsyncClient, ASGITransport
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


async def test_api_get_mcp_servers(app):
    with patch("dashboard.server.get_mcp_status", return_value=[
        {"name": "fs", "status": "connected", "tools": ["fs__read"], "uptime_seconds": 42.0}
    ]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/mcp/servers")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "fs"


async def test_api_disable_unknown_server(app):
    with patch("dashboard.server.disable_mcp_server", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/mcp/servers/unknown/disable")
    assert r.status_code == 404


async def test_api_disable_known_server(app):
    with patch("dashboard.server.disable_mcp_server", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/mcp/servers/fs/disable")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_api_restart_mcp(app):
    with patch("dashboard.server.restart_mcp_servers", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/mcp/restart")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Config editor API tests
# ---------------------------------------------------------------------------

async def test_api_get_mcp_config_no_file(app, tmp_path):
    with patch.object(mcp_mod, "_MCP_CONFIG", tmp_path / "missing.json"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/mcp/config")
    assert r.status_code == 200
    assert r.json() == []


async def test_api_get_mcp_config_existing(app, tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/mcp/config")
    assert r.status_code == 200
    assert r.json() == [{"name": "fs", "command": ["npx"]}]


async def test_api_get_mcp_config_corrupted(app, tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text("not json")
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/mcp/config")
    assert r.status_code == 200
    assert r.json() == []


async def test_api_put_mcp_config_valid(app, tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    new_config = [{"name": "git", "command": ["npx", "-y", "@mcp/git"]}]
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/mcp/config", json=new_config)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert json.loads(cfg.read_text()) == new_config


async def test_api_put_mcp_config_not_a_list(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.put("/api/mcp/config", json={"not": "a list"})
    assert r.status_code == 422
    assert "error" in r.json()


async def test_api_put_mcp_config_invalid_json_body(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.put(
            "/api/mcp/config",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 422
    assert "error" in r.json()


async def test_api_put_mcp_config_invalid_config(app, tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    with patch.object(mcp_mod, "_MCP_CONFIG", cfg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # missing 'name' field — _validate_configs raises ValueError
            r = await client.put("/api/mcp/config", json=[{"command": ["npx"]}])
    assert r.status_code == 422
    data = r.json()
    assert "error" in data
    assert "name" in data["error"]
