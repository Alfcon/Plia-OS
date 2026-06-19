# MCP Client Integration Design

**Date:** 2026-06-19
**Status:** Approved

## Overview

Add a local MCP (Model Context Protocol) client to Plia-OS so external tool servers can register tools into the existing `@tool` registry. MCP servers run as subprocesses on the same machine, communicate over stdio, and are spawned once at app startup. From the rest of the codebase's perspective, MCP tools look identical to built-in `@tool` functions.

---

## Section 1: Architecture

### Transport

**stdio only.** Each MCP server is a local subprocess. Communication is JSON-RPC 2.0 over stdin/stdout. No HTTP, no SSE, no remote servers. This is the right choice for a voice assistant where latency matters — stdio adds ~1–5ms per tool call vs. ~50–200ms for an HTTP round-trip to localhost, and avoids the operational complexity of managing server ports and TLS.

### SDK

Official `mcp` Python SDK (`pip install mcp`). Added as an optional extra (`pip install -e ".[mcp]"`). If not installed, `load_mcp_servers()` is a silent no-op — the rest of the app is unaffected.

### Connection lifetime

**Persistent connections via `AsyncExitStack`.** Each MCP server subprocess is spawned once at app startup and kept alive for the app's lifetime. Tool calls are pipe I/O only — no re-spawning per call. Torn down cleanly on app shutdown via `AsyncExitStack.aclose()`.

### Tool registration

MCP tools are registered into the existing `_tools` dict in `core/registry.py` using the same schema format as `@tool`-decorated functions. They are indistinguishable from built-in tools at call time. Async wrappers are used since MCP tool calls are inherently async.

### Tool naming

`servername__toolname` (double underscore separator). Server name comes from `mcp_servers.json`. Example: a server named `filesystem` with a tool `read_file` registers as `filesystem__read_file`. Collisions are skipped with a warning log.

### Disabled modules

MCP tools use `mcp:{server_name}` as their module identifier, matching the `disabled_modules` filtering in `core/loader.py`. To disable all tools from a server, add `"mcp:filesystem"` to `disabled_modules` in config.

---

## Section 2: Config Format

User-managed file at `~/.plia/mcp_servers.json`. Separate from `PliaConfig` — not persisted to `~/.plia/config.json`, not exposed via `POST /api/config`. Edited by hand or by future tooling.

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
| `name` | string | yes | Tool prefix. No `__` allowed. Must be unique. |
| `command` | list[str] | yes | `command[0]` = executable, rest = args. |
| `env` | dict[str, str] | no | Extra env vars merged with current process env. |

If `~/.plia/mcp_servers.json` does not exist, `load_mcp_servers()` returns immediately — no error, no log noise.

---

## Section 3: Connection Lifecycle (`core/mcp_client.py`)

```python
import asyncio, json, logging
from contextlib import AsyncExitStack
from pathlib import Path

logger = logging.getLogger(__name__)
_MCP_CONFIG = Path.home() / ".plia" / "mcp_servers.json"
_exit_stack = AsyncExitStack()
_sessions: dict[str, Any] = {}   # server_name → ClientSession

async def load_mcp_servers() -> None:
    """Called once at app startup, after load_modules()."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return   # mcp extra not installed — silent no-op

    if not _MCP_CONFIG.exists():
        return

    try:
        servers = json.loads(_MCP_CONFIG.read_text())
    except Exception:
        logger.warning("mcp_servers.json unreadable — skipping MCP", exc_info=True)
        return

    await _exit_stack.__aenter__()

    for cfg in servers:
        name = cfg.get("name", "")
        cmd  = cfg.get("command", [])
        env  = cfg.get("env") or None
        try:
            params    = StdioServerParameters(command=cmd[0], args=cmd[1:], env=env)
            transport = await _exit_stack.enter_async_context(stdio_client(params))
            session   = await _exit_stack.enter_async_context(ClientSession(*transport))
            await session.initialize()
            _sessions[name] = session
            await _register_tools(name, session)
            logger.info("MCP server %r connected", name)
        except Exception:
            logger.warning("MCP server %r failed", name, exc_info=True)

async def shutdown_mcp_servers() -> None:
    """Called on app shutdown — closes all subprocess pipes cleanly."""
    await _exit_stack.aclose()

async def _register_tools(name: str, session) -> None:
    from core.registry import _tools
    response = await session.list_tools()
    for t in response.tools:
        prefixed = f"{name}__{t.name}"
        if prefixed in _tools:
            logger.warning("MCP tool %r conflicts with existing tool — skipped", prefixed)
            continue
        _capture = (name, t.name)
        async def _fn(_n=_capture[0], _t=_capture[1], **kwargs):
            try:
                result = await _sessions[_n].call_tool(_t, kwargs)
                return "\n".join(
                    c.text for c in result.content if hasattr(c, "text")
                ) or "Done."
            except Exception as e:
                return f"MCP error ({_n}/{_t}): {e}"
        _tools[prefixed] = {
            "fn": _fn,
            "module": f"mcp:{name}",
            "schema": {
                "type": "function",
                "function": {
                    "name": prefixed,
                    "description": t.description or prefixed,
                    "parameters": t.inputSchema,
                },
            },
        }
        logger.debug("Registered MCP tool %r", prefixed)
```

**`core/main.py` additions:**

```python
from core.mcp_client import load_mcp_servers, shutdown_mcp_servers

# in lifespan, after load_modules():
await load_mcp_servers()

# in shutdown:
await shutdown_mcp_servers()
```

---

## Section 4: Registry Change + Supervisor Update

### `core/registry.py` — add `call_tool_async`

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

Existing `call_tool()` stays untouched. All existing sync callers (tests, other code) are unaffected.

### `core/supervisor.py` line 156 — one line change

```python
# Before:
result = call_tool(fn["name"], fn.get("arguments") or {})

# After:
result = await call_tool_async(fn["name"], fn.get("arguments") or {})
```

Update import:

```python
from core.registry import get_tool_schemas, call_tool_async
```

`respond` node is already `async def` so `await` is valid. Sync tools pass through `call_tool_async` unchanged via the `inspect.iscoroutinefunction` branch.

---

## Section 5: Error Handling + Testing

### Error handling — three layers

**1. Config load (`load_mcp_servers`):**
- `mcp` not installed → silent no-op
- `mcp_servers.json` missing → silent no-op
- `mcp_servers.json` unparseable → log warning, skip all MCP
- Individual server fails to spawn → log warning, skip that server, continue
- App starts normally regardless of MCP state

**2. Tool call (async wrapper):**
- `session.call_tool()` raises any exception → caught, returns `f"MCP error ({server_name}/{tool_name}): {e}"` as a string
- Respond node returns this as a message rather than crashing the turn

**3. Dead session (subprocess died mid-run):**
- `call_tool` raises → caught by wrapper above, returns error string
- No reconnect logic in v1 — restart app to reconnect

### Testing

**`tests/test_mcp_client.py`** — unit tests, mock the SDK:

```python
@pytest.mark.asyncio
async def test_load_skips_if_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr("core.mcp_client._MCP_CONFIG", tmp_path / "nope.json")
    await load_mcp_servers()   # no-op, no raise

async def test_load_skips_if_mcp_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", None)
    await load_mcp_servers()   # ImportError caught, no-op

async def test_tool_registered_with_prefix(mock_session):
    # mock_session.list_tools() returns [Tool(name="read", ...)]
    await _register_tools("fs", mock_session)
    assert "fs__read" in _tools

async def test_tool_call_returns_text(mock_session):
    # mock_session.call_tool() returns content with text "hello"
    await _register_tools("fs", mock_session)
    result = await _tools["fs__read"]["fn"](path="/tmp/x")
    assert result == "hello"

async def test_tool_call_error_returns_string(mock_session):
    mock_session.call_tool.side_effect = RuntimeError("pipe broken")
    await _register_tools("fs", mock_session)
    result = await _tools["fs__read"]["fn"]()
    assert "MCP error" in result

async def test_collision_skipped(mock_session, caplog):
    _tools["fs__read"] = {"fn": lambda: None, "schema": {}}
    await _register_tools("fs", mock_session)
    assert "conflicts" in caplog.text
```

**`tests/test_registry_async.py`** — `call_tool_async` behavior:

```python
async def test_async_tool_awaited():
    async def my_tool(): return "async"
    _tools["t"] = {"fn": my_tool, "schema": {}}
    assert await call_tool_async("t", {}) == "async"

async def test_sync_tool_called():
    def my_tool(): return "sync"
    _tools["t"] = {"fn": my_tool, "schema": {}}
    assert await call_tool_async("t", {}) == "sync"

async def test_unknown_tool_raises():
    with pytest.raises(KeyError, match="Unknown tool"):
        await call_tool_async("nonexistent", {})
```

No integration test spawning a real MCP subprocess — that belongs in manual smoke testing, not CI.

---

## Optional Extra

```toml
# pyproject.toml
[project.optional-dependencies]
mcp = ["mcp>=1.0"]
```

Install: `pip install -e ".[mcp]"`

---

## Files Changed

| File | Change |
|------|--------|
| `core/mcp_client.py` | Create — ~90 lines |
| `core/registry.py` | Add `call_tool_async` (~10 lines), add `import inspect` |
| `core/supervisor.py` | Line 156: `call_tool` → `await call_tool_async`; update import |
| `core/main.py` | Add `load_mcp_servers()` after `load_modules()`; `shutdown_mcp_servers()` in shutdown |
| `pyproject.toml` | Add `mcp = ["mcp>=1.0"]` optional extra |
| `tests/test_mcp_client.py` | Create — ~50 lines |
| `tests/test_registry_async.py` | Create — ~30 lines |

No new agents, no new LangGraph nodes, no new `_KEYWORD_ROUTES` entries. MCP tools are discovered by the LLM at call time via `get_tool_schemas()` like any other tool.
