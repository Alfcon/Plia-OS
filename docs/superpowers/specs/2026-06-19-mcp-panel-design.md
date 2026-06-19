# MCP Panel Design

**Date:** 2026-06-19
**Status:** Approved

## Overview

Add a dashboard settings tab that shows connected MCP servers, their health status, and tool counts. Allows disabling individual servers at runtime and restarting the full MCP subsystem to re-enable.

## Backend (`core/mcp_client.py`)

### `get_mcp_status() -> list[dict]`

Reads `~/.plia/mcp_servers.json` (returns `[]` if missing or invalid). For each configured server returns:

```python
{
    "name": str,
    "status": "connected" | "disabled" | "failed",
    "tools": list[str],          # empty if never connected
    "uptime_seconds": float | None  # None if not connected
}
```

Status rules:
- `"connected"` — name in `_servers` and `healthy=True`
- `"disabled"` — name in `_disabled_servers`
- `"failed"` — name not in `_servers` and not in `_disabled_servers` (failed at startup)

### `disable_mcp_server(name: str) -> bool`

Adds `name` to `_disabled_servers`. If name is in `_servers`, sets `_servers[name].healthy = False`. Returns `False` if name not found in config (unknown server), `True` on success.

### `restart_mcp_servers()` (async)

Protected by module-level `_restart_lock: asyncio.Lock`. Sequence:
1. `await _exit_stack.aclose()`
2. Reset: `_exit_stack = AsyncExitStack()`, `_servers.clear()`, `_disabled_servers.clear()`, `_initialized = False`
3. `await load_mcp_servers()`

## API Endpoints (`dashboard/server.py`)

```
GET  /api/mcp/servers              → list[dict] from get_mcp_status()
POST /api/mcp/servers/{name}/disable → {"ok": true} or 404
POST /api/mcp/restart              → {"ok": true}
```

`POST /api/mcp/servers/{name}/disable` returns HTTP 404 if `disable_mcp_server(name)` returns `False`.

`POST /api/mcp/restart` fires `await restart_mcp_servers()` inline (not a background task — client waits for reconnection before getting 200).

## Dashboard Panel (`dashboard/static/index.html`)

New "MCP" nav button added between Modules and Home in `#m-nav`:

```html
<button class="m-nav-btn" data-section="mcp" onclick="showMenuSection('mcp');loadMcpServers()">MCP</button>
```

New pane `#m-section-mcp` added between `#m-section-modules` and `#m-section-home`:

```
MCP Servers                    [↻ Restart MCP]
──────────────────────────────────────────────
● filesystem   connected  3 tools  2h 14m  [Disable]
○ github       disabled   4 tools           [—]
✕ puppeteer    failed     —                 [—]
──────────────────────────────────────────────
(empty state) No MCP servers configured.
```

### Status indicators

| Symbol | Color | Meaning |
|--------|-------|---------|
| `●` | `#4caf50` (green) | connected, healthy |
| `○` | `#555` (gray) | disabled |
| `✕` | `#e53935` (red) | failed to start |

### Uptime formatting (`formatUptime(seconds)`)

- `< 60s` → `"45s"`
- `< 3600s` → `"14m 32s"`
- `≥ 3600s` → `"2h 14m"`
- `null` → `"—"`

### Disable button

Active (blue) only for `status === "connected"`. Grayed out and non-clickable for `disabled` or `failed`. On click: `POST /api/mcp/servers/{name}/disable`, then `loadMcpServers()`.

### Restart button

`POST /api/mcp/restart`. On click: disables button, shows `"Restarting…"`, waits 1500ms after response, then `loadMcpServers()` and re-enables button. The 1500ms gives the server time to finish reconnecting before the list refreshes.

### `loadMcpServers()`

`GET /api/mcp/servers` → renders list into `#mcp-servers-list`. On error shows inline error message. Called on tab open.

## Testing (`tests/test_mcp_panel.py`)

Uses the same autouse reset fixture as `tests/test_mcp_client.py` to reset `_servers`, `_disabled_servers`, `_initialized`, `_exit_stack` before each test.

### Unit tests for `core/mcp_client.py`

- `get_mcp_status()` returns `[]` when config file absent
- `get_mcp_status()` returns `status="failed"` for server in `_disabled_servers` but not `_servers`
- `get_mcp_status()` returns `status="connected"` with correct tool list and non-None uptime for server in `_servers`
- `get_mcp_status()` returns `status="disabled"` for server in both `_servers` and `_disabled_servers`
- `disable_mcp_server("unknown")` returns `False`
- `disable_mcp_server(name)` adds to `_disabled_servers` and sets `healthy=False`
- `restart_mcp_servers()` clears `_servers`, `_disabled_servers`, resets `_initialized` to `False`

### API endpoint tests via `AsyncClient`

- `GET /api/mcp/servers` returns 200 with a list
- `POST /api/mcp/servers/unknown/disable` returns 404
- `POST /api/mcp/servers/{name}/disable` returns 200 with `{"ok": true}`
- `POST /api/mcp/restart` returns 200 with `{"ok": true}`

## No changes needed

- `core/registry.py` — MCP tools already registered via `register_tool()`
- `core/supervisor.py` — no routing change
- `core/main.py` — startup/shutdown unchanged
- All existing MCP tests — no regressions expected
