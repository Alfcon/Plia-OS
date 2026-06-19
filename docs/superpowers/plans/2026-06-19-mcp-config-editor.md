# MCP Config Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a JSON textarea to the MCP settings panel so users can view and edit `~/.plia/mcp_servers.json` from the dashboard.

**Architecture:** Two tasks — backend API endpoints with tests, then the dashboard HTML/JS additions. The backend exposes `GET /api/mcp/config` (read) and `PUT /api/mcp/config` (validate + write). The dashboard adds a textarea below the existing server list and two JS functions.

**Tech Stack:** Python (FastAPI, JSONResponse), vanilla JS, HTML/CSS inline styles.

## Global Constraints

- No new dependencies
- Response body for 422 errors: `{"error": "..."}` (not FastAPI's default `{"detail": ...}`)
- `PUT /api/mcp/config` writes JSON with `indent=2` (2-space pretty-print)
- `GET /api/mcp/config` returns `[]` (not an error) when file is absent
- Textarea id: `mcp-config-editor`; status span id: `mcp-config-status`
- Inline styles only — no external CSS
- `asyncio_mode = "auto"` in pytest.ini — no `@pytest.mark.asyncio` decorator
- Run full suite: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: API endpoints + tests

**Files:**
- Modify: `dashboard/server.py`
- Modify: `tests/test_mcp_panel.py`

**Interfaces:**
- Consumes:
  - `core.mcp_client._MCP_CONFIG: Path` — `Path.home() / ".plia" / "mcp_servers.json"`
  - `core.mcp_client._validate_configs(servers: list[dict]) -> None` — raises `ValueError` on invalid config
- Produces:
  - `GET /api/mcp/config` → `list[dict]`
  - `PUT /api/mcp/config` → `{"ok": True}` or HTTP 422 `{"error": "..."}`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_mcp_panel.py` (the file already exists — add only these new functions at the bottom; do not duplicate imports already present):

```python
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
```

Note: `json` is already imported at the top of `test_mcp_panel.py`. Do not re-import it.

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_mcp_panel.py -k "config" --tb=short -q
```

Expected: FAILED — endpoints not defined yet.

- [ ] **Step 3: Add `JSONResponse` to imports in `dashboard/server.py`**

Find line 11:
```python
from fastapi.responses import HTMLResponse
```

Replace with:
```python
from fastapi.responses import HTMLResponse, JSONResponse
```

- [ ] **Step 4: Add `GET /api/mcp/config` and `PUT /api/mcp/config` to `dashboard/server.py`**

Add these two endpoints immediately after the `restart_mcp_endpoint` function (after line 791, before the blank line that precedes `@router.websocket("/ws")`):

```python
@router.get("/api/mcp/config")
async def get_mcp_config():
    from core.mcp_client import _MCP_CONFIG
    if not _MCP_CONFIG.exists():
        return []
    try:
        return json.loads(_MCP_CONFIG.read_text())
    except Exception:
        return []


@router.put("/api/mcp/config")
async def put_mcp_config(request: Request):
    from core.mcp_client import _MCP_CONFIG, _validate_configs
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": f"Invalid JSON: {e}"})
    if not isinstance(body, list):
        return JSONResponse(status_code=422, content={"error": "Config must be a JSON array"})
    try:
        _validate_configs(body)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})
    _MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _MCP_CONFIG.write_text(json.dumps(body, indent=2))
    return {"ok": True}
```

- [ ] **Step 5: Run config tests — verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_mcp_panel.py -k "config" --tb=short -q
```

Expected: 5 tests pass.

- [ ] **Step 6: Run full suite — verify no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: 695 passed (690 + 5 new).

- [ ] **Step 7: Commit**

```bash
git add dashboard/server.py tests/test_mcp_panel.py
git commit -m "feat(mcp): add GET/PUT /api/mcp/config endpoints for config editor"
```

---

### Task 2: Dashboard HTML and JS

**Files:**
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes:
  - `GET /api/mcp/config` → `list[dict]`
  - `PUT /api/mcp/config` → `{"ok": True}` or HTTP 422 `{"error": "..."}`
- Produces: visible config textarea in MCP panel; `loadMcpConfig()` and `saveMcpConfig()` global JS functions

There are no automated tests for dashboard HTML. Verification: run pytest for regressions, then inspect in browser.

- [ ] **Step 1: Add config HTML to `#m-section-mcp` pane**

Find this exact block (currently lines 1083–1084):

```html
          <ul id="mcp-servers-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
        </div>
```

Replace with:

```html
          <ul id="mcp-servers-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
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
        </div>
```

- [ ] **Step 2: Update MCP nav button to also load config**

Find this exact line (currently line 715):

```html
        <button class="m-nav-btn" data-section="mcp" onclick="showMenuSection('mcp');loadMcpServers()">MCP</button>
```

Replace with:

```html
        <button class="m-nav-btn" data-section="mcp" onclick="showMenuSection('mcp');loadMcpServers();loadMcpConfig()">MCP</button>
```

- [ ] **Step 3: Add `loadMcpConfig()` and `saveMcpConfig()` JS functions**

Find the blank line after the closing brace of `restartMcp()` (currently line 1917, immediately after `}`):

```javascript
  }

  async function loadModules() {
```

Insert the two new functions between `restartMcp()` and `loadModules()`:

```javascript
  async function loadMcpConfig() {
    const ta = document.getElementById('mcp-config-editor');
    try {
      const r = await fetch('/api/mcp/config');
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      ta.value = JSON.stringify(data, null, 2);
    } catch(e) {
      ta.value = '// Failed to load config';
    }
  }

  async function saveMcpConfig() {
    const ta = document.getElementById('mcp-config-editor');
    const status = document.getElementById('mcp-config-status');
    status.style.color = '#888';
    status.textContent = 'Saving…';
    let parsed;
    try {
      parsed = JSON.parse(ta.value);
    } catch(e) {
      status.style.color = '#ef9a9a';
      status.textContent = `Invalid JSON: ${e.message}`;
      return;
    }
    try {
      const r = await fetch('/api/mcp/config', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(parsed),
      });
      if (r.status === 422) {
        const data = await r.json();
        status.style.color = '#ef9a9a';
        status.textContent = data.error || 'Validation error';
        return;
      }
      if (!r.ok) throw new Error(r.status);
      status.style.color = '#81c784';
      status.textContent = 'Saved. Click ↻ Restart MCP to apply.';
    } catch(e) {
      status.style.color = '#ef9a9a';
      status.textContent = 'Save failed.';
    }
  }

```

- [ ] **Step 4: Run Python suite — verify no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: 695 passed.

- [ ] **Step 5: Smoke-test in the browser**

Start server:
```bash
source .venv/bin/activate && python core/main.py
```

Open `http://localhost:8000`. Open Settings → MCP. Verify:

- [ ] Config textarea appears below server list, separated by a thin rule
- [ ] Textarea loads current `~/.plia/mcp_servers.json` as pretty-printed JSON (or `[]` if absent)
- [ ] Edit the JSON and click Save Config — status shows green "Saved. Click ↻ Restart MCP to apply."
- [ ] Enter invalid JSON and click Save Config — status shows red "Invalid JSON: ..."
- [ ] Enter valid JSON with missing `name` field and click Save Config — status shows red validation error
- [ ] Click ↻ Restart MCP after saving — servers list refreshes with updated config

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add MCP config editor textarea to MCP panel"
```
