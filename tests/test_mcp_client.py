import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.mcp_client as mcp_mod
from core.mcp_client import (
    _MCPServer,
    _register_tools,
    _validate_configs,
    load_mcp_servers,
    shutdown_mcp_servers,
)
from core.registry import ToolExecutionError, _tools, clear_tools, register_tool


@pytest.fixture(autouse=True)
def reset_mcp_state():
    """Reset all module-level mcp_client state before and after each test."""
    from contextlib import AsyncExitStack
    mcp_mod._servers.clear()
    mcp_mod._disabled_servers.clear()
    mcp_mod._initialized = False
    mcp_mod._exit_stack = AsyncExitStack()
    yield
    mcp_mod._servers.clear()
    mcp_mod._disabled_servers.clear()
    mcp_mod._initialized = False
    mcp_mod._exit_stack = AsyncExitStack()


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def test_validate_rejects_missing_name():
    with pytest.raises(ValueError, match="missing 'name'"):
        _validate_configs([{"command": ["npx"]}])


def test_validate_rejects_empty_name():
    with pytest.raises(ValueError, match="missing 'name'"):
        _validate_configs([{"name": "", "command": ["npx"]}])


def test_validate_rejects_dunder_in_name():
    with pytest.raises(ValueError, match="must not contain"):
        _validate_configs([{"name": "a__b", "command": ["npx"]}])


def test_validate_rejects_duplicate_name():
    with pytest.raises(ValueError, match="Duplicate"):
        _validate_configs([
            {"name": "fs", "command": ["x"]},
            {"name": "fs", "command": ["y"]},
        ])


def test_validate_rejects_empty_command():
    with pytest.raises(ValueError, match="non-empty list"):
        _validate_configs([{"name": "fs", "command": []}])


def test_validate_rejects_empty_executable():
    with pytest.raises(ValueError, match="non-empty list"):
        _validate_configs([{"name": "fs", "command": [""]}])


def test_validate_passes_valid_config():
    _validate_configs([{"name": "fs", "command": ["npx", "-y", "some-server"]}])


def test_validate_passes_with_env():
    _validate_configs([{"name": "fs", "command": ["npx"], "env": {"KEY": "val"}}])


# ---------------------------------------------------------------------------
# load_mcp_servers: no-op cases
# ---------------------------------------------------------------------------

async def test_load_skips_if_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr("core.mcp_client._MCP_CONFIG", tmp_path / "nope.json")
    await load_mcp_servers()
    assert not mcp_mod._servers


async def test_load_skips_if_mcp_not_installed(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "fs", "command": ["npx"]}]))
    monkeypatch.setattr("core.mcp_client._MCP_CONFIG", cfg)
    with patch.dict(sys.modules, {"mcp": None, "mcp.client": None, "mcp.client.stdio": None}):
        await load_mcp_servers()
    assert not mcp_mod._servers


async def test_double_init_is_noop(caplog):
    mcp_mod._initialized = True
    await load_mcp_servers()
    assert "called twice" in caplog.text


async def test_invalid_json_skips_all(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text("not json{{")
    monkeypatch.setattr("core.mcp_client._MCP_CONFIG", cfg)
    await load_mcp_servers()
    assert not mcp_mod._servers


async def test_config_validation_failure_skips_all(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps([{"name": "a__b", "command": ["npx"]}]))
    monkeypatch.setattr("core.mcp_client._MCP_CONFIG", cfg)
    await load_mcp_servers()
    assert not mcp_mod._servers


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def _make_fake_tool(name="read", description="read a file", schema=None):
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = schema or {"type": "object", "properties": {"path": {"type": "string"}}}
    return t


def _make_mock_session(*tools):
    s = MagicMock()
    s.list_tools = AsyncMock(return_value=MagicMock(tools=list(tools)))
    s.call_tool = AsyncMock()
    return s


async def test_tool_registered_with_prefix():
    clear_tools()
    fake = _make_fake_tool("read")
    session = _make_mock_session(fake)
    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server

    await _register_tools("fs", server)

    assert "fs__read" in _tools
    assert _tools["fs__read"]["module"] == "mcp:fs"
    assert _tools["fs__read"]["meta"]["source"] == "mcp"
    assert _tools["fs__read"]["meta"]["server"] == "fs"
    assert _tools["fs__read"]["meta"]["tool"] == "read"
    assert "fs__read" in server.tools


async def test_invalid_schema_falls_back(caplog):
    clear_tools()
    fake = _make_fake_tool("bad", schema=None)
    fake.inputSchema = None   # invalid
    session = _make_mock_session(fake)
    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server

    await _register_tools("fs", server)

    params = _tools["fs__bad"]["schema"]["function"]["parameters"]
    assert params == {"type": "object", "properties": {}}
    assert "invalid inputSchema" in caplog.text


async def test_invalid_schema_list_falls_back(caplog):
    clear_tools()
    fake = _make_fake_tool("bad2")
    fake.inputSchema = ["not", "a", "dict"]
    session = _make_mock_session(fake)
    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server

    await _register_tools("fs", server)

    params = _tools["fs__bad2"]["schema"]["function"]["parameters"]
    assert params == {"type": "object", "properties": {}}


async def test_collision_skipped(caplog):
    clear_tools()
    register_tool(name="fs__read", fn=lambda: None, description="existing", parameters={})
    fake = _make_fake_tool("read")
    session = _make_mock_session(fake)
    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server

    await _register_tools("fs", server)

    assert "already registered" in caplog.text
    assert len(server.tools) == 0


# ---------------------------------------------------------------------------
# Tool call behavior
# ---------------------------------------------------------------------------

async def test_tool_call_returns_text():
    clear_tools()
    content = MagicMock()
    content.text = "file contents here"
    mock_result = MagicMock()
    mock_result.content = [content]

    fake = _make_fake_tool("read")
    session = _make_mock_session(fake)
    session.call_tool = AsyncMock(return_value=mock_result)

    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server
    await _register_tools("fs", server)

    result = await _tools["fs__read"]["fn"](path="/tmp/x")
    assert result == "file contents here"


async def test_tool_call_multiple_content_items_joined():
    clear_tools()
    c1, c2 = MagicMock(), MagicMock()
    c1.text = "line 1"
    c2.text = "line 2"
    mock_result = MagicMock()
    mock_result.content = [c1, c2]

    fake = _make_fake_tool("list")
    session = _make_mock_session(fake)
    session.call_tool = AsyncMock(return_value=mock_result)

    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server
    await _register_tools("fs", server)

    result = await _tools["fs__list"]["fn"]()
    assert result == "line 1\nline 2"


async def test_tool_call_empty_content_returns_done():
    clear_tools()
    mock_result = MagicMock()
    mock_result.content = []

    fake = _make_fake_tool("write")
    session = _make_mock_session(fake)
    session.call_tool = AsyncMock(return_value=mock_result)

    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server
    await _register_tools("fs", server)

    result = await _tools["fs__write"]["fn"]()
    assert result == "Done."


async def test_tool_call_timeout_marks_server_unhealthy():
    import asyncio
    clear_tools()
    mcp_mod._disabled_servers.discard("fs")

    async def hang(*a, **kw):
        await asyncio.sleep(9999)

    fake = _make_fake_tool("slow")
    session = _make_mock_session(fake)
    session.call_tool = hang

    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server
    await _register_tools("fs", server)

    original_timeout = mcp_mod._TOOL_TIMEOUT
    mcp_mod._TOOL_TIMEOUT = 0.05
    try:
        with pytest.raises(ToolExecutionError, match="timed out"):
            await _tools["fs__slow"]["fn"]()
    finally:
        mcp_mod._TOOL_TIMEOUT = original_timeout

    assert "fs" in mcp_mod._disabled_servers
    assert not server.healthy


async def test_tool_call_exception_marks_server_unhealthy():
    clear_tools()
    mcp_mod._disabled_servers.discard("fs")

    fake = _make_fake_tool("broken")
    session = _make_mock_session(fake)
    session.call_tool = AsyncMock(side_effect=RuntimeError("pipe broke"))

    server = _MCPServer(session=session)
    mcp_mod._servers["fs"] = server
    await _register_tools("fs", server)

    with pytest.raises(ToolExecutionError, match="pipe broke"):
        await _tools["fs__broken"]["fn"]()

    assert "fs" in mcp_mod._disabled_servers
    assert not server.healthy


async def test_disabled_server_raises_immediately_without_calling_session():
    clear_tools()
    mcp_mod._disabled_servers.add("fs3")

    fake = _make_fake_tool("read")
    session = _make_mock_session(fake)

    server = _MCPServer(session=session)
    mcp_mod._servers["fs3"] = server
    await _register_tools("fs3", server)

    with pytest.raises(ToolExecutionError, match="disabled"):
        await _tools["fs3__read"]["fn"]()

    session.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

async def test_shutdown_safe_when_no_servers_started():
    await shutdown_mcp_servers()   # must not raise
