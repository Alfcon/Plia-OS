# MCP Client Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local MCP (Model Context Protocol) stdio client so external tool servers can register tools into Plia's existing `@tool` registry, making MCP tools indistinguishable from built-in tools at call time.

**Architecture:** A new `core/mcp_client.py` manages persistent subprocess connections via `AsyncExitStack`, validates config from `~/.plia/mcp_servers.json`, and registers MCP tools into `core/registry.py` using a new `register_tool()` API. The supervisor's respond node is updated to use a new async-capable `call_tool_async()` that properly awaits coroutine tools. All existing sync tools continue to work unchanged.

**Tech Stack:** Python 3.11+, `mcp>=1.0` (optional extra), `asyncio`, `contextlib.AsyncExitStack`, official MCP Python SDK (`mcp.client.stdio`).

## Global Constraints

- `mcp` is an optional dependency — if not installed, all MCP code must be a silent no-op. App starts normally with or without it.
- No new LangGraph agents, no new `_KEYWORD_ROUTES` entries, no new `_KNOWN_INTENTS`.
- MCP tool names use `servername__toolname` format (double underscore). Server names must not contain `__`.
- MCP tools use `f"mcp:{server_name}"` as their `module` identifier — this makes them filterable via `disabled_modules` in config.
- `register_tool()` returns `False` on name collision (does NOT raise) — unlike `@tool` decorator which raises `ValueError`.
- Tool call timeout: `_TOOL_TIMEOUT = 30` seconds (module-level constant in `core/mcp_client.py`).
- After any tool call failure (timeout or exception), the server is added to `_disabled_servers` and marked `healthy = False`. Subsequent calls to that server raise `ToolExecutionError` immediately.
- `_initialized` flag prevents double-init in `load_mcp_servers()`.
- Config validation runs before any subprocess is spawned — all entries validated or all MCP is skipped.
- Do NOT call `_exit_stack.__aenter__()` explicitly — use `enter_async_context()` directly.

---

### Task 1: Registry additions — `ToolExecutionError`, `register_tool()`, `call_tool_async()`

**Files:**
- Modify: `core/registry.py`
- Create: `tests/test_registry_async.py`

**Interfaces:**
- Consumes: existing `_tools: dict[str, dict]` and `_disabled_modules()` in `core/registry.py`
- Produces:
  - `ToolExecutionError(Exception)` — raised by MCP tool wrappers on failure
  - `register_tool(*, name, fn, description, parameters, module="", meta=None) -> bool` — inserts into `_tools`, returns `False` on collision
  - `call_tool_async(name: str, arguments: dict) -> Any` — async dispatcher, awaits async tools, calls sync tools directly, checks disabled modules

- [ ] **Step 1: Write all failing tests**

Create `tests/test_registry_async.py`:

```python
import pytest
from core.registry import (
    ToolExecutionError,
    call_tool_async,
    register_tool,
    _tools,
    clear_tools,
)


# ToolExecutionError

def test_tool_execution_error_is_exception():
    e = ToolExecutionError("boom")
    assert isinstance(e, Exception)
    assert str(e) == "boom"


# register_tool

def test_register_tool_adds_entry():
    def fn(): return "ok"
    result = register_tool(
        name="my_fn",
        fn=fn,
        description="does a thing",
        parameters={"type": "object", "properties": {}},
    )
    assert result is True
    assert "my_fn" in _tools
    assert _tools["my_fn"]["fn"] is fn
    assert _tools["my_fn"]["schema"]["function"]["name"] == "my_fn"
    assert _tools["my_fn"]["schema"]["function"]["description"] == "does a thing"


def test_register_tool_collision_returns_false_and_leaves_original():
    def fn1(): return "first"
    def fn2(): return "second"
    register_tool(name="dup", fn=fn1, description="", parameters={})
    result = register_tool(name="dup", fn=fn2, description="", parameters={})
    assert result is False
    assert _tools["dup"]["fn"] is fn1   # original untouched


def test_register_tool_stores_module():
    def fn(): pass
    register_tool(name="t_mod", fn=fn, description="", parameters={}, module="mcp:fs")
    assert _tools["t_mod"]["module"] == "mcp:fs"


def test_register_tool_stores_meta():
    def fn(): pass
    meta = {"source": "mcp", "server": "fs", "tool": "read"}
    register_tool(name="t_meta", fn=fn, description="", parameters={}, meta=meta)
    assert _tools["t_meta"]["meta"] == meta


def test_register_tool_no_meta_field_when_none():
    def fn(): pass
    register_tool(name="t_nometa", fn=fn, description="", parameters={})
    assert "meta" not in _tools["t_nometa"]


# call_tool_async

async def test_call_tool_async_awaits_async_tool():
    async def async_fn(): return "async_result"
    register_tool(name="t_async", fn=async_fn, description="", parameters={})
    result = await call_tool_async("t_async", {})
    assert result == "async_result"


async def test_call_tool_async_calls_sync_tool():
    def sync_fn(): return "sync_result"
    register_tool(name="t_sync", fn=sync_fn, description="", parameters={})
    result = await call_tool_async("t_sync", {})
    assert result == "sync_result"


async def test_call_tool_async_passes_arguments():
    def add(x: int, y: int): return x + y
    register_tool(name="t_add", fn=add, description="", parameters={})
    result = await call_tool_async("t_add", {"x": 3, "y": 4})
    assert result == 7


async def test_call_tool_async_unknown_tool_raises_key_error():
    with pytest.raises(KeyError, match="Unknown tool"):
        await call_tool_async("does_not_exist", {})
```

- [ ] **Step 2: Run tests — verify all fail**

```bash
source .venv/bin/activate
pytest tests/test_registry_async.py -v
```

Expected: all fail with `ImportError` (`ToolExecutionError`, `register_tool`, `call_tool_async` not yet defined).

- [ ] **Step 3: Add `ToolExecutionError`, `register_tool()`, `call_tool_async()` to `core/registry.py`**

Open `core/registry.py`. Add after the existing imports at the top (after line 3, before `_tools = ...`):

```python
import logging

logger = logging.getLogger(__name__)
```

Then add these three definitions after the existing `list_modules()` function and before `clear_tools()`:

```python
class ToolExecutionError(Exception):
    """Raised by tool wrappers (e.g. MCP) on execution failure."""


def register_tool(
    *,
    name: str,
    fn: Callable,
    description: str,
    parameters: dict,
    module: str = "",
    meta: dict | None = None,
) -> bool:
    """Register a tool by name. Returns False (logs warning) on collision."""
    if name in _tools:
        logger.warning("Tool %r already registered — skipped", name)
        return False
    entry: dict = {
        "fn": fn,
        "module": module,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    }
    if meta is not None:
        entry["meta"] = meta
    _tools[name] = entry
    return True


async def call_tool_async(name: str, arguments: dict) -> Any:
    """Async-capable tool dispatch. Awaits coroutine tools, calls sync tools directly."""
    if name not in _tools:
        raise KeyError(f"Unknown tool: {name!r}")
    entry = _tools[name]
    if entry["module"] in _disabled_modules():
        raise KeyError(f"Tool {name!r} is in a disabled module")
    fn = entry["fn"]
    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)
```

The full `core/registry.py` after changes:

```python
import inspect
import logging
from typing import Any, Callable, get_type_hints

logger = logging.getLogger(__name__)

_tools: dict[str, dict] = {}
_LOADING_MODULE: str = ""

_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


def _build_parameters(fn: Callable) -> dict:
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        py_type = hints.get(name, str)
        properties[name] = {"type": _TYPE_MAP.get(py_type, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def set_loading_module(name: str) -> None:
    global _LOADING_MODULE
    _LOADING_MODULE = name


def tool(description: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        name = fn.__name__
        if name in _tools:
            raise ValueError(f"Tool {name!r} already registered")
        _tools[name] = {
            "fn": fn,
            "module": _LOADING_MODULE,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": _build_parameters(fn),
                },
            },
        }
        return fn
    return decorator


def _disabled_modules() -> set[str]:
    from core.config import get_config
    return set(get_config().disabled_modules)


def get_tool_schemas() -> list[dict]:
    disabled = _disabled_modules()
    return [
        entry["schema"] for entry in _tools.values()
        if entry["module"] not in disabled
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name not in _tools:
        raise KeyError(f"Tool {name!r} not found")
    entry = _tools[name]
    if entry["module"] in _disabled_modules():
        raise KeyError(f"Tool {name!r} is in a disabled module")
    return entry["fn"](**arguments)


def list_tools() -> dict[str, str]:
    return {
        name: entry["schema"]["function"]["description"]
        for name, entry in _tools.items()
    }


def list_modules() -> dict[str, list[str]]:
    """Returns {module_name: [tool_names]} for all registered tools."""
    result: dict[str, list[str]] = {}
    for name, entry in _tools.items():
        mod = entry["module"] or "unknown"
        result.setdefault(mod, []).append(name)
    return result


class ToolExecutionError(Exception):
    """Raised by tool wrappers (e.g. MCP) on execution failure."""


def register_tool(
    *,
    name: str,
    fn: Callable,
    description: str,
    parameters: dict,
    module: str = "",
    meta: dict | None = None,
) -> bool:
    """Register a tool by name. Returns False (logs warning) on collision."""
    if name in _tools:
        logger.warning("Tool %r already registered — skipped", name)
        return False
    entry: dict = {
        "fn": fn,
        "module": module,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    }
    if meta is not None:
        entry["meta"] = meta
    _tools[name] = entry
    return True


async def call_tool_async(name: str, arguments: dict) -> Any:
    """Async-capable tool dispatch. Awaits coroutine tools, calls sync tools directly."""
    if name not in _tools:
        raise KeyError(f"Unknown tool: {name!r}")
    entry = _tools[name]
    if entry["module"] in _disabled_modules():
        raise KeyError(f"Tool {name!r} is in a disabled module")
    fn = entry["fn"]
    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)


def clear_tools() -> None:
    """For testing only."""
    _tools.clear()
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
pytest tests/test_registry_async.py -v
```

Expected: all 11 PASSED.

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
pytest --tb=short -q
```

Expected: all passing (560+ tests). Fix any failures before continuing.

- [ ] **Step 6: Commit**

```bash
git add core/registry.py tests/test_registry_async.py
git commit -m "feat(registry): add ToolExecutionError, register_tool, call_tool_async"
```

---

### Task 2: MCP client module

**Files:**
- Create: `core/mcp_client.py`
- Create: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes (from Task 1): `register_tool()`, `ToolExecutionError` from `core.registry`
- Produces:
  - `load_mcp_servers() -> None` — called at app startup (async)
  - `shutdown_mcp_servers() -> None` — called at app shutdown (async)
  - `_validate_configs(servers: list[dict]) -> None` — raises `ValueError` on bad config
  - `_MCPServer` dataclass — fields: `session`, `healthy: bool`, `tools: list[str]`, `lock: asyncio.Lock`, `started_at: float`
  - Module-level: `_servers: dict[str, _MCPServer]`, `_disabled_servers: set[str]`, `_initialized: bool`, `_TOOL_TIMEOUT: int = 30`

- [ ] **Step 1: Write all failing tests**

Create `tests/test_mcp_client.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify all fail**

```bash
pytest tests/test_mcp_client.py -v
```

Expected: all fail with `ModuleNotFoundError` (file doesn't exist yet).

- [ ] **Step 3: Create `core/mcp_client.py`**

```python
import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MCP_CONFIG = Path.home() / ".plia" / "mcp_servers.json"
_TOOL_TIMEOUT: int = 30

_exit_stack = AsyncExitStack()
_initialized: bool = False


@dataclass
class _MCPServer:
    session: Any
    healthy: bool = True
    tools: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started_at: float = field(default_factory=time.monotonic)


_servers: dict[str, _MCPServer] = {}
_disabled_servers: set[str] = set()


def _validate_configs(servers: list[dict]) -> None:
    seen: set[str] = set()
    for cfg in servers:
        name = cfg.get("name")
        if not name:
            raise ValueError(f"MCP server config missing 'name': {cfg!r}")
        if "__" in name:
            raise ValueError(f"MCP server name {name!r} must not contain '__'")
        if name in seen:
            raise ValueError(f"Duplicate MCP server name: {name!r}")
        cmd = cfg.get("command")
        if not cmd or not cmd[0]:
            raise ValueError(
                f"MCP server {name!r}: 'command' must be a non-empty list with a non-empty executable"
            )
        seen.add(name)


async def load_mcp_servers() -> None:
    global _initialized
    if _initialized:
        logger.warning("load_mcp_servers() called twice — skipping")
        return
    _initialized = True

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return

    if not _MCP_CONFIG.exists():
        return

    try:
        servers = json.loads(_MCP_CONFIG.read_text())
        _validate_configs(servers)
    except Exception:
        logger.warning("mcp_servers.json invalid — skipping MCP", exc_info=True)
        return

    for cfg in servers:
        name = cfg["name"]
        cmd = cfg["command"]
        env = cfg.get("env") or None
        try:
            params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=env)
            transport = await _exit_stack.enter_async_context(stdio_client(params))
            session = await _exit_stack.enter_async_context(ClientSession(*transport))
            await session.initialize()
            server = _MCPServer(session=session)
            _servers[name] = server
            await _register_tools(name, server)
            logger.info("MCP server %r connected (%d tools)", name, len(server.tools))
        except Exception:
            logger.warning("MCP server %r failed to start — skipped", name, exc_info=True)
            _disabled_servers.add(name)


async def shutdown_mcp_servers() -> None:
    await _exit_stack.aclose()


async def _register_tools(name: str, server: _MCPServer) -> None:
    from core.registry import ToolExecutionError, register_tool

    response = await server.session.list_tools()
    for t in response.tools:
        prefixed = f"{name}__{t.name}"

        schema = t.inputSchema
        if not isinstance(schema, dict):
            logger.warning(
                "MCP tool %r has invalid inputSchema (%r) — using empty schema",
                prefixed,
                type(schema).__name__,
            )
            schema = {"type": "object", "properties": {}}

        _n, _t = name, t.name

        async def _fn(_n: str = _n, _t: str = _t, **kwargs: Any) -> str:
            if _n in _disabled_servers:
                raise ToolExecutionError(f"MCP server {_n!r} is disabled after failure")
            async with _servers[_n].lock:
                try:
                    result = await asyncio.wait_for(
                        _servers[_n].session.call_tool(_t, kwargs),
                        timeout=_TOOL_TIMEOUT,
                    )
                    return (
                        "\n".join(c.text for c in result.content if hasattr(c, "text"))
                        or "Done."
                    )
                except asyncio.TimeoutError:
                    _servers[_n].healthy = False
                    _disabled_servers.add(_n)
                    raise ToolExecutionError(
                        f"MCP server {_n!r} timed out after {_TOOL_TIMEOUT}s — marked unhealthy"
                    )
                except Exception as e:
                    _servers[_n].healthy = False
                    _disabled_servers.add(_n)
                    raise ToolExecutionError(
                        f"MCP server {_n!r} error on {_t!r}: {e}"
                    ) from e

        registered = register_tool(
            name=prefixed,
            fn=_fn,
            description=t.description or prefixed,
            parameters=schema,
            module=f"mcp:{name}",
            meta={"source": "mcp", "server": name, "tool": t.name},
        )
        if registered:
            server.tools.append(prefixed)
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
pytest tests/test_mcp_client.py -v
```

Expected: all 27 PASSED.

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
pytest --tb=short -q
```

Expected: all passing. Fix any failures before continuing.

- [ ] **Step 6: Commit**

```bash
git add core/mcp_client.py tests/test_mcp_client.py
git commit -m "feat(mcp): add MCP stdio client with persistent connections and tool registration"
```

---

### Task 3: Wiring — supervisor, main.py, pyproject.toml

**Files:**
- Modify: `core/supervisor.py` (lines 8, 155–160)
- Modify: `core/main.py` (imports + lifespan)
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes (from Task 1): `call_tool_async`, `ToolExecutionError` from `core.registry`
- Consumes (from Task 2): `load_mcp_servers`, `shutdown_mcp_servers` from `core.mcp_client`
- Produces: nothing new — wires existing pieces together

**No new tests needed** — the wiring is three small edits. The full suite (which includes tests that hit `create_app()` via `ASGITransport`) verifies end-to-end correctness.

- [ ] **Step 1: Update `core/supervisor.py` import line**

Line 8 currently reads:
```python
from core.registry import get_tool_schemas, call_tool
```

Change to:
```python
from core.registry import get_tool_schemas, call_tool_async, ToolExecutionError
```

- [ ] **Step 2: Update `core/supervisor.py` tool-call site**

Lines 155–160 currently read:
```python
            try:
                result = call_tool(fn["name"], fn.get("arguments") or {})
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                result = f"Error: {exc}"
```

Replace with:
```python
            try:
                result = await call_tool_async(fn["name"], fn.get("arguments") or {})
            except ToolExecutionError as e:
                result = f"[Tool error: {e}]"
            except Exception as exc:
                result = f"Error: {exc}"
```

The `if inspect.isawaitable` lines are removed — `call_tool_async` handles sync/async dispatch internally.

- [ ] **Step 3: Update `core/main.py`**

Add one import after the existing imports (e.g., after line 14):
```python
from core.mcp_client import load_mcp_servers, shutdown_mcp_servers
```

Inside the `lifespan` async context manager, add `await load_mcp_servers()` before `yield` and `await shutdown_mcp_servers()` in the shutdown block. The full updated lifespan:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            import psutil
            psutil.cpu_percent()
        except ImportError:
            pass
        await load_mcp_servers()
        pipeline_task = asyncio.create_task(start_pipeline())
        pipeline_registry.set_task(pipeline_task)
        reminder_task = asyncio.create_task(run_reminder_loop())
        yield
        pipeline_task.cancel()
        reminder_task.cancel()
        for task in (pipeline_task, reminder_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        await shutdown_mcp_servers()
```

- [ ] **Step 4: Add `mcp` optional extra to `pyproject.toml`**

In the `[project.optional-dependencies]` section, add after `airllm = [...]`:
```toml
mcp = ["mcp>=1.0"]
```

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
source .venv/bin/activate
pytest --tb=short -q
```

Expected: all passing. The `load_mcp_servers()` call in `create_app()` lifespan is a no-op when `~/.plia/mcp_servers.json` doesn't exist (which is true in the test environment).

- [ ] **Step 6: Commit**

```bash
git add core/supervisor.py core/main.py pyproject.toml
git commit -m "feat(mcp): wire MCP client into app startup and supervisor tool dispatch"
```

---

## Post-implementation smoke test (manual)

After all three tasks are committed:

1. Install the optional extra:
   ```bash
   pip install -e ".[mcp]"
   ```

2. Create `~/.plia/mcp_servers.json` with a real server (example uses `@modelcontextprotocol/server-filesystem`, requires Node.js):
   ```json
   [
     {
       "name": "filesystem",
       "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
     }
   ]
   ```

3. Start Plia:
   ```bash
   python core/main.py
   ```

4. Check logs for:
   ```
   core.mcp_client: MCP server 'filesystem' connected (N tools)
   ```

5. Open `http://localhost:8000` and ask: *"List the files in /tmp"* — the LLM should see `filesystem__list_directory` in its tool schemas and call it.
