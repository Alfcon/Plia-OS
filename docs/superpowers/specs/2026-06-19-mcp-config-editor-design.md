# MCP Config Editor Design

**Date:** 2026-06-19
**Status:** Approved

## Overview

Add a JSON textarea to the existing MCP settings panel that lets users view and edit `~/.plia/mcp_servers.json` directly from the dashboard, without leaving the browser.

## Backend (`dashboard/server.py`)

### `GET /api/mcp/config`

Reads `~/.plia/mcp_servers.json` and returns its contents as a JSON array. Returns `[]` if the file does not exist. Never returns an error for a missing file.

### `PUT /api/mcp/config`

Request body: a JSON array (the full new config).

1. Parse body as JSON — return HTTP 422 `{"error": "Invalid JSON: ..."}` on parse failure.
2. Run `_validate_configs(body)` from `core.mcp_client` — return HTTP 422 `{"error": "<validation message>"}` on failure.
3. Write the validated config to `~/.plia/mcp_servers.json` (pretty-printed, 2-space indent).
4. Return `{"ok": True}`.

Save does not trigger a restart. The existing "↻ Restart MCP" button applies the saved config.

## Dashboard Panel (`dashboard/static/index.html`)

The config editor is appended to the bottom of the existing `#m-section-mcp` pane, below the server list, separated by a thin rule:

```
MCP Servers                    [↻ Restart MCP]
──────────────────────────────────────────────
[server list rows]
──────────────────────────────────────────────
Config
[textarea — pretty-printed JSON, monospace font, 8 rows]
[Save Config]   status line: "Saved. Click ↻ Restart MCP to apply." or red error
```

### `loadMcpConfig()`

Called alongside `loadMcpServers()` when the MCP tab opens. `GET /api/mcp/config` → pretty-print result with `JSON.stringify(data, null, 2)` → set as textarea value. On error: set textarea value to `"// Failed to load config"`.

### Save button

Calls `saveMcpConfig()`:
1. Parse `textarea.value` as JSON — show red `"Invalid JSON"` inline if parse fails (no network call).
2. `PUT /api/mcp/config` with body = `JSON.stringify(parsed)`.
3. On 200: show green `"Saved. Click ↻ Restart MCP to apply."`.
4. On 422: show red `data.error` from response body.
5. On network error: show red `"Save failed."`.

### HTML structure added to `#m-section-mcp`

```html
<hr style="border:none;border-top:1px solid #1a1a1a;margin:10px 0 8px;">
<div style="font-size:0.75rem;color:#aaa;margin-bottom:4px;">Config</div>
<textarea id="mcp-config-editor"
  style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#eee;
         padding:6px;border-radius:3px;font-size:0.72rem;font-family:monospace;
         resize:vertical;min-height:120px;"
  rows="8" spellcheck="false"></textarea>
<div style="display:flex;align-items:center;gap:8px;margin-top:6px;">
  <button onclick="saveMcpConfig()"
    style="background:#1565c0;border:none;color:#eee;padding:4px 10px;border-radius:3px;
           font-size:0.75rem;cursor:pointer;">Save Config</button>
  <span id="mcp-config-status" style="font-size:0.72rem;color:#888;"></span>
</div>
```

## Testing (`tests/test_mcp_panel.py`)

New API tests appended to the existing file, using the existing `app` fixture:

- `GET /api/mcp/config` returns `[]` when `~/.plia/mcp_servers.json` absent (patched path)
- `GET /api/mcp/config` returns the parsed array when file exists
- `PUT /api/mcp/config` with valid config → 200 `{"ok": True}`, file written with correct content
- `PUT /api/mcp/config` with unparseable body → 422 `{"error": ...}`
- `PUT /api/mcp/config` with valid JSON but failing `_validate_configs` → 422 `{"error": ...}`

## No changes needed

- `core/mcp_client.py` — `_validate_configs` already exported; no new functions needed
- `core/main.py` — no changes
- All existing tests — no regressions expected
