# MCP Client Integration Design

**Date:** 2026-06-19
**Status:** Approved (rev 2 — post-review improvements incorporated)

## Overview

Add a local MCP (Model Context Protocol) client to Plia-OS so external tool servers can register tools into the existing `@tool` registry. MCP servers run as subprocesses on the same machine, communicate over stdio, and are spawned once at app startup. From the rest of the codebase's perspective, MCP tools look identical to built-in `@tool` functions.

---

## Section 1: Architecture

### Transport

**stdio only.** Each MCP server is a local subprocess. Communication is JSON-RPC 2.0 over stdin/stdout. No HTTP, no SSE, no remote servers. Stdio adds ~1–5ms per tool call vs. ~50–200ms for HTTP round-trips, and avoids port/TLS complexity.

### SDK

Official `mcp` Python SDK (`pip install mcp`). Added as optional extra (`pip install -e ".[mcp]"`). If not installed, `load_mcp_servers()` is a silent no-op.

### Connection lifetime

**Persistent connections via `AsyncExitStack`.** Each subprocess spawned once at startup, alive for app lifetime. Tool calls are pipe I/O only — no re-spawning per call. Torn down cleanly on shutdown via `AsyncExitStack.aclose()`.

**Single initialization guard:** `_initialized` flag prevents accidental double-init from future refactors (duplicate tool registration, duplicate subprocess spawning).

### Tool registration

MCP tools registered into `_tools` via `register_tool()` (a thin wrapper in `core/registry.py`, not direct dict mutation). Same schema format as `@tool`-decorated functions. Indistinguishable from built-in tools at call time.

**Tool discovery occurs only at startup. Runtime-added tools require app restart.**

### Tool naming

`servername__toolname` (double underscore separator). Collisions skipped with warning log.

### Disabled modules

MCP tools use `mcp:{server_name}` as module identifier. To disable all tools from a server: add `"mcp:filesystem"` to `disabled_modules` in config.

### Security note

> **MCP servers execute with the same OS privileges as Plia.** `mcp_servers.json` is equivalent to a list of trusted executables. Treat it accordingly — do not add servers from untrusted sources.

---

## Section 2: Config Format

User-managed file at `~/.plia/mcp_servers.json`. Separate from `PliaConfig`. Edited by hand.

```json
[
  {
    "name": "filesystem",
    "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home/user/Documents"]
  },
  {
    "name": "git",
    "command": ["uvx", "mcp-server-git", "--repository", "/home/user/Projects"],
    "env": {"GIT_AUTHOR_NAME": "Plia"}
  }
]
```

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Tool prefix. No `__`. Must be unique across all entries. |
| `command` | list[str] | yes | `command[0]` = executable, rest = args. Both must be non-empty. |
| `env` | dict[str, str] | no | Extra env vars merged with process env. |

All entries validated before any subprocess is spawned (see Section 3). If `mcp_servers.json` missing, no-op.

---

## Section 3: Connection Lifecycle (`core/mcp_client.py`)

### Server registry structure

Replace a bare `_sessions` dict with a richer per-server object. Avoids future refactor when health, metrics, or reconnect is added:

```python
from dataclasses import dataclass, field
import asyncio, time

@dataclass
class _MCPServer:
    session: Any
    healthy: bool = True
    tools: list[str] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started_at: float = field(default_factory=time.monotonic)

_servers: dict[str, _MCPServer] = {}
_disabled_servers: set[str] = set()
_initialized: bool = False
_exit_stack = AsyncExitStack()
_TOOL_TIMEOUT = 30   # seconds; hard-coded for v1
```

### Config validation

Validate all entries before spawning anything:

```python
def _validate_configs(servers: list[dict]) -> None:
    seen: set[str] = set()
    for cfg in servers:
        name = cfg.get("name")
        if not name:
            raise ValueError("MCP server config missing 'name'")
        if "__" in name:
            raise ValueError(f"MCP server name {name!r} must not contain '__'")
        if name in seen:
            raise ValueError(f"Duplicate MCP server name: {name!r}")
        cmd = cfg.get("command")
        if not cmd or not cmd[0]:
            raise ValueError(f"MCP server {name!r}: 'command' must be a non-empty list with a non-empty executable")
        seen.add(name)
```

Validation failure logs an error and skips all MCP — app continues normally.

### Startup

```python
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

    await _exit_stack.__aenter__()

    for cfg in servers:
        name = cfg["name"]
        cmd  = cfg["command"]
        env  = cfg.get("env") or None
        try:
            params    = StdioServerParameters(command=cmd[0], args=cmd[1:], env=env)
            transport = await _exit_stack.enter_async_context(stdio_client(params))
            session   = await _exit_stack.enter_async_context(ClientSession(*transport))
            await session.initialize()
            server = _MCPServer(session=session)
            _servers[name] = server
            await _register_tools(name, server)
            logger.info("MCP server %r connected (%d tools)", name, len(server.tools))
        except Exception:
            # One server fails → log, mark disabled, continue with others
            logger.warning("MCP server %r failed to start — skipped", name, exc_info=True)
            _disabled_servers.add(name)

async def shutdown_mcp_servers() -> None:
    """Safe to call even if only some servers started."""
    await _exit_stack.aclose()
```

### Tool registration

```python
async def _register_tools(name: str, server: _MCPServer) -> None:
    from core.registry import register_tool
    response = await server.session.list_tools()
    for t in response.tools:
        prefixed = f"{name}__{t.name}"
        # Validate/fallback schema — many MCP servers generate imperfect schemas
        schema = t.inputSchema
        if not isinstance(schema, dict):
            logger.warning(
                "MCP tool %r has invalid inputSchema (%r) — using empty schema",
                prefixed, type(schema).__name__
            )
            schema = {"type": "object", "properties": {}}

        _n, _t = name, t.name
        async def _fn(_n=_n, _t=_t, **kwargs):
            if _n in _disabled_servers:
                raise ToolExecutionError(f"MCP server {_n!r} is disabled after failure")
            async with _servers[_n].lock:
                try:
                    result = await asyncio.wait_for(
                        _servers[_n].session.call_tool(_t, kwargs),
                        timeout=_TOOL_TIMEOUT,
                    )
                    return "\n".join(
                        c.text for c in result.content if hasattr(c, "text")
                    ) or "Done."
                except asyncio.TimeoutError:
                    _servers[_n].healthy = False
                    _disabled_servers.add(_n)
                    raise ToolExecutionError(
                        f"MCP server {_n!r} timed out after {_TOOL_TIMEOUT}s — marked unhealthy"
                    )
                except Exception as e:
                    _servers[_n].healthy = False
                    _disabled_servers.add(_n)
                    raise ToolExecutionError(f"MCP server {_n!r} error on {_t!r}: {e}") from e

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

### `core/main.py` additions

```python
from core.mcp_client import load_mcp_servers, shutdown_mcp_servers

# in lifespan, after load_modules():
await load_mcp_servers()

# in shutdown:
await shutdown_mcp_servers()
```

---

## Section 4: Registry Changes (`core/registry.py`)

### Add `ToolExecutionError`

```python
class ToolExecutionError(Exception):
    """Raised by tools (including MCP wrappers) on execution failure."""
```

### Add `register_tool()`

Thin wrapper around `_tools` mutation — enables future validation, metrics, permission checks without touching MCP code:

```python
def register_tool(
    *,
    name: str,
    fn,
    description: str,
    parameters: dict,
    module: str = "",
    meta: dict | None = None,
) -> bool:
    """Returns True if registered, False if name collided."""
    if name in _tools:
        logger.warning("Tool %r already registered — skipped", name)
        return False
    _tools[name] = {
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
        **({"meta": meta} if meta else {}),
    }
    return True
```

### Add `call_tool_async()`

```python
import inspect

async def call_tool_async(name: str, arguments: dict):
    entry = _tools.get(name)
    if entry is None:
        raise KeyError(f"Unknown tool: {name}")
    fn = entry["fn"]
    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)
```

Existing `call_tool()` stays untouched.

### Update supervisor (`core/supervisor.py` line 156)

```python
# Before:
result = call_tool(fn["name"], fn.get("arguments") or {})

# After:
try:
    result = await call_tool_async(fn["name"], fn.get("arguments") or {})
except ToolExecutionError as e:
    result = f"[Tool error: {e}]"
```

Update import:

```python
from core.registry import get_tool_schemas, call_tool_async, ToolExecutionError
```

`[Tool error: ...]` is distinguishable from genuine tool output — the brackets and prefix mark it as infrastructure-level, not user data. The LLM sees it and can report failure naturally. A future supervisor refactor can promote this to a structured error path when tool chaining is added.

---

## Section 5: Error Handling

| Failure | Detection | Action |
|---------|-----------|--------|
| `mcp` not installed | `ImportError` at startup | Silent no-op |
| `mcp_servers.json` missing | `Path.exists()` | Silent no-op |
| `mcp_servers.json` unparseable | `json.JSONDecodeError` | Log warning, skip all MCP |
| Config validation failure | `ValueError` from `_validate_configs` | Log error, skip all MCP |
| Server fails to spawn | Exception in startup loop | Log warning, add to `_disabled_servers`, continue |
| Tool call times out | `asyncio.TimeoutError` | Mark server unhealthy, add to `_disabled_servers`, raise `ToolExecutionError` |
| Tool call raises | Any `Exception` | Mark server unhealthy, add to `_disabled_servers`, raise `ToolExecutionError` |
| Call to disabled server | Check `_disabled_servers` before `call_tool` | Raise `ToolExecutionError` immediately |

**No reconnect in v1.** Restart app to reconnect dead servers. Unhealthy servers are skipped on subsequent calls rather than repeatedly hitting a dead pipe.

---

## Section 6: Testing

**`tests/test_mcp_client.py`:**

```python
# Config validation
def test_validate_rejects_empty_name():
    with pytest.raises(ValueError, match="missing 'name'"):
        _validate_configs([{"name": "", "command": ["npx"]}])

def test_validate_rejects_dunder_in_name():
    with pytest.raises(ValueError, match="must not contain"):
        _validate_configs([{"name": "a__b", "command": ["x"]}])

def test_validate_rejects_duplicate_name():
    with pytest.raises(ValueError, match="Duplicate"):
        _validate_configs([{"name": "fs", "command": ["x"]}, {"name": "fs", "command": ["y"]}])

def test_validate_rejects_empty_command():
    with pytest.raises(ValueError, match="non-empty list"):
        _validate_configs([{"name": "fs", "command": []}])

# Startup
@pytest.mark.asyncio
async def test_load_skips_if_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr("core.mcp_client._MCP_CONFIG", tmp_path / "nope.json")
    await load_mcp_servers()   # no raise

async def test_load_skips_if_mcp_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", None)
    await load_mcp_servers()   # ImportError caught, no-op

async def test_double_init_skipped(caplog):
    await load_mcp_servers()
    await load_mcp_servers()
    assert "called twice" in caplog.text

# Partial startup failure
async def test_partial_failure_good_servers_register(mock_session_factory):
    # filesystem → succeeds; git → raises on initialize(); browser → succeeds
    # Verify: filesystem and browser tools registered, git in _disabled_servers
    ...

# Tool registration
async def test_tool_registered_with_prefix(mock_session):
    await _register_tools("fs", MCPServer(session=mock_session))
    assert "fs__read" in _tools

async def test_invalid_schema_falls_back(mock_session_bad_schema):
    # list_tools returns Tool with inputSchema = None
    await _register_tools("fs", MCPServer(session=mock_session_bad_schema))
    entry = _tools["fs__read"]
    assert entry["schema"]["function"]["parameters"] == {"type": "object", "properties": {}}

async def test_collision_skipped(mock_session, caplog):
    _tools["fs__read"] = {"fn": lambda: None, "schema": {}}
    await _register_tools("fs", MCPServer(session=mock_session))
    assert "already registered" in caplog.text

# Tool calls
async def test_tool_call_returns_text(mock_session):
    # mock_session.call_tool() returns content with text "hello"
    server = MCPServer(session=mock_session)
    _servers["fs"] = server
    await _register_tools("fs", server)
    result = await _tools["fs__read"]["fn"](path="/tmp/x")
    assert result == "hello"

async def test_tool_call_timeout_disables_server(mock_session_hanging):
    server = MCPServer(session=mock_session_hanging)
    _servers["fs"] = server
    await _register_tools("fs", server)
    with pytest.raises(ToolExecutionError, match="timed out"):
        await _tools["fs__read"]["fn"]()
    assert "fs" in _disabled_servers
    assert not server.healthy

async def test_disabled_server_raises_immediately():
    _disabled_servers.add("fs")
    _servers["fs"] = MCPServer(session=MagicMock())
    await _register_tools("fs", _servers["fs"])
    with pytest.raises(ToolExecutionError, match="disabled"):
        await _tools["fs__read"]["fn"]()

# Shutdown
async def test_shutdown_after_partial_init():
    # Only filesystem started; git never entered exit_stack
    await shutdown_mcp_servers()   # no raise
```

**`tests/test_registry_async.py`:**

```python
async def test_async_tool_awaited():
    async def my_tool(): return "async"
    register_tool(name="t", fn=my_tool, description="", parameters={})
    assert await call_tool_async("t", {}) == "async"

async def test_sync_tool_called():
    def my_tool(): return "sync"
    register_tool(name="t", fn=my_tool, description="", parameters={})
    assert await call_tool_async("t", {}) == "sync"

async def test_unknown_tool_raises():
    with pytest.raises(KeyError, match="Unknown tool"):
        await call_tool_async("nonexistent", {})

def test_register_tool_collision_returns_false():
    register_tool(name="x", fn=lambda: None, description="", parameters={})
    result = register_tool(name="x", fn=lambda: None, description="", parameters={})
    assert result is False
```

No integration test spawning a real MCP subprocess — manual smoke testing only.

---

## Future Enhancements (not v1)

- **Per-server tool allowlist:** `"allowed_tools": ["read_file", "write_file"]` in config
- **Reconnect logic:** exponential backoff on `_disabled_servers`, background health-check task
- **Dynamic tool discovery:** re-call `list_tools()` on demand (requires restart-free reload path)
- **Dashboard panel:** show connected servers, health status, registered tool count

---

## Files Changed

| File | Change |
|------|--------|
| `core/mcp_client.py` | Create — ~120 lines |
| `core/registry.py` | Add `ToolExecutionError`, `register_tool()`, `call_tool_async()`, `import inspect` |
| `core/supervisor.py` | Line 156: `await call_tool_async(...)` + `ToolExecutionError` catch; update import |
| `core/main.py` | `load_mcp_servers()` after `load_modules()`; `shutdown_mcp_servers()` in shutdown |
| `pyproject.toml` | Add `mcp = ["mcp>=1.0"]` optional extra |
| `tests/test_mcp_client.py` | Create — ~90 lines |
| `tests/test_registry_async.py` | Create — ~30 lines |

No new agents, no new LangGraph nodes, no new `_KEYWORD_ROUTES` entries.
