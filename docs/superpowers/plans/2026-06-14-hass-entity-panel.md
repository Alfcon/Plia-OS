# Home Assistant Entity Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an entity list to the dashboard Home section that shows lights and switches from Home Assistant and lets users toggle them with a button click.

**Architecture:** Two new endpoints — `GET /api/hass/entities` returns structured entity data for lights and switches, `POST /api/hass/toggle/{entity_id}` fires the `toggle` service. A new `list_entities()` helper in `agents/home_assistant.py` handles the structured return (existing `list_states()` returns a string for voice use). The dashboard Home section already has HA URL/token config; the entity list is appended below it and loaded on nav click.

**Tech Stack:** httpx (existing), FastAPI (existing), vanilla JS fetch (existing), `agents/home_assistant.py` (existing async functions)

---

## File Map

| File | Change |
|------|--------|
| `agents/home_assistant.py` | Add `list_entities(base_url, token, domains)` returning `list[dict]` |
| `dashboard/server.py` | Add `GET /api/hass/entities` and `POST /api/hass/toggle/{entity_id}` |
| `tests/test_hass_api.py` | New — 4 endpoint tests |
| `dashboard/static/index.html` | Entity list HTML in Home section + `loadHassEntities()` + `toggleHassEntity()` JS |

---

### Task 1: `list_entities()` + API endpoints + tests

**Files:**
- Modify: `agents/home_assistant.py`
- Modify: `dashboard/server.py`
- Create: `tests/test_hass_api.py`

**Context:**

`agents/home_assistant.py` currently has:
- `call_service(base_url, token, domain, service, entity_id, extra)` — async, POSTs to HA services API
- `list_states(base_url, token, domain)` — async, returns formatted **string** (for voice agent — not usable for dashboard JSON)

`dashboard/server.py` imports:
- `get_config` from `core.config` (already imported at line 14)
- `asyncio` (already imported at line 1)
- No HA imports exist yet

Default `PliaConfig` has `hass_url: str = ""` and `hass_token: str = ""` — empty when not configured.

- [ ] **Step 1: Write failing tests**

Create `tests/test_hass_api.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_entities_returns_empty_when_not_configured(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/hass/entities")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_entities_returns_list_when_configured(app):
    fake_entities = [
        {"entity_id": "light.living_room", "friendly_name": "Living Room", "state": "on", "domain": "light"},
        {"entity_id": "switch.fan", "friendly_name": "Fan", "state": "off", "domain": "switch"},
    ]
    with patch("core.config._config") as mock_cfg, \
         patch("agents.home_assistant.list_entities", new=AsyncMock(return_value=fake_entities)):
        mock_cfg.hass_url = "http://homeassistant.local:8123"
        mock_cfg.hass_token = "abc123"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/hass/entities")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["entity_id"] == "light.living_room"
    assert data[0]["state"] == "on"


@pytest.mark.asyncio
async def test_toggle_returns_503_when_not_configured(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/hass/toggle/light.living_room")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_toggle_calls_correct_service(app):
    with patch("core.config._config") as mock_cfg, \
         patch("agents.home_assistant.call_service", new=AsyncMock(return_value="Called light.toggle on light.living_room")):
        mock_cfg.hass_url = "http://homeassistant.local:8123"
        mock_cfg.hass_token = "abc123"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/hass/toggle/light.living_room")
    assert r.status_code == 200
    assert "result" in r.json()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_hass_api.py -v
```

Expected: FAIL (404 — routes don't exist yet).

- [ ] **Step 3: Add `list_entities()` to `agents/home_assistant.py`**

Append after the existing `list_states` function (at end of file):

```python


async def list_entities(
    base_url: str, token: str, domains: list[str] | None = None
) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/states"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=_headers(token))
    resp.raise_for_status()
    entities = resp.json()
    if domains:
        entities = [e for e in entities if e.get("entity_id", "").split(".")[0] in domains]
    result = []
    for e in entities:
        eid = e.get("entity_id", "")
        domain = eid.split(".")[0] if "." in eid else ""
        result.append({
            "entity_id": eid,
            "friendly_name": e.get("attributes", {}).get("friendly_name", eid),
            "state": e.get("state", "unknown"),
            "domain": domain,
        })
    return result
```

- [ ] **Step 4: Add endpoints to `dashboard/server.py`**

Read the file to find `@router.get("/api/tools")` (currently around line 77–82). Insert the two HA routes immediately before it:

```python
@router.get("/api/hass/entities")
async def hass_entities():
    config = get_config()
    if not config.hass_url or not config.hass_token:
        return []
    from agents.home_assistant import list_entities
    return await list_entities(config.hass_url, config.hass_token, domains=["light", "switch"])


@router.post("/api/hass/toggle/{entity_id}")
async def hass_toggle(entity_id: str):
    config = get_config()
    if not config.hass_url or not config.hass_token:
        raise HTTPException(status_code=503, detail="Home Assistant not configured")
    domain = entity_id.split(".")[0]
    from agents.home_assistant import call_service
    result = await call_service(config.hass_url, config.hass_token, domain, "toggle", entity_id)
    return {"result": result}


```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_hass_api.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agents/home_assistant.py dashboard/server.py tests/test_hass_api.py
git commit -m "feat(hass): add list_entities() and GET/POST /api/hass endpoints"
```

---

### Task 2: Entity list UI in dashboard Home section

**Files:**
- Modify: `dashboard/static/index.html`

No backend tests — pure HTML/JS. The Home section (`#m-section-home`) already shows the HA URL/token config form at lines 327–337. We append the entity list below the existing `#hass-status` div and load it when the user clicks the "Home" nav button.

**UI:** entities grouped by domain (all lights then all switches), each row shows friendly name + state badge (green = on, grey = off) + "Toggle" button. If HA not configured, shows a prompt to save credentials first.

- [ ] **Step 1: Add entity list HTML to Home section**

Find this exact line in `dashboard/static/index.html`:
```html
          <div id="hass-status" style="font-size:0.72rem;margin-top:6px;color:#888;"></div>
```

Add immediately after it (before the closing `</div>` of `m-section-home`):
```html
          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:14px;margin-bottom:6px;">
            <span style="font-size:0.78rem;color:#aaa;">Entities</span>
            <button onclick="loadHassEntities()" style="background:none;border:none;color:#4fc3f7;font-size:0.75rem;cursor:pointer;">↻ Refresh</button>
          </div>
          <ul id="hass-entities-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
```

- [ ] **Step 2: Update Home nav button to load entities**

Find this exact line:
```html
        <button class="m-nav-btn" data-section="home" onclick="showMenuSection('home')">Home</button>
```

Replace with:
```html
        <button class="m-nav-btn" data-section="home" onclick="showMenuSection('home');loadHassEntities()">Home</button>
```

- [ ] **Step 3: Add JS functions**

Find the `saveHassConfig` function (around line 867). Add the following two functions immediately before it:

```javascript
  async function loadHassEntities() {
    const list = document.getElementById('hass-entities-list');
    list.innerHTML = '<li style="color:#555;font-size:0.75rem;">Loading…</li>';
    try {
      const r = await fetch('/api/hass/entities');
      if (!r.ok) throw new Error(r.status);
      const entities = await r.json();
      if (!Array.isArray(entities) || entities.length === 0) {
        list.innerHTML = '<li style="color:#555;font-size:0.75rem;">No entities found. Save HA credentials above.</li>';
        return;
      }
      list.innerHTML = entities.map(e => {
        const on = e.state === 'on' || e.state === 'open';
        const badge = `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${on ? '#81c784' : '#555'};margin-right:5px;"></span>`;
        return `<li style="padding:5px 0;border-bottom:1px solid #1a1a1a;display:flex;justify-content:space-between;align-items:center;gap:6px;">
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${badge}${_esc(e.friendly_name)}</span>
          <button onclick="toggleHassEntity(this, ${JSON.stringify(e.entity_id)})"
            style="background:#1e1e1e;border:1px solid #333;border-radius:3px;color:#aaa;font-size:0.7rem;padding:2px 8px;cursor:pointer;flex-shrink:0;">Toggle</button>
        </li>`;
      }).join('');
    } catch(e) {
      list.innerHTML = '<li style="color:#ef9a9a;font-size:0.75rem;">Failed to load entities</li>';
    }
  }

  async function toggleHassEntity(btn, entityId) {
    btn.disabled = true;
    btn.textContent = '…';
    try {
      const r = await fetch('/api/hass/toggle/' + encodeURIComponent(entityId), {method: 'POST'});
      if (!r.ok) throw new Error(r.status);
    } catch(e) {
      btn.textContent = '✕';
      return;
    }
    await loadHassEntities();
  }

```

- [ ] **Step 4: Run full suite for regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add Home Assistant entity list with toggle to Home section"
```

---

## Self-Review

**Spec coverage:**
- ✅ `GET /api/hass/entities` — returns lights + switches as structured JSON
- ✅ `POST /api/hass/toggle/{entity_id}` — fires `{domain}.toggle` service
- ✅ 503 when HA not configured (toggle), empty list when not configured (entities)
- ✅ `list_entities()` returns `[{entity_id, friendly_name, state, domain}]`
- ✅ Dashboard entity list in Home section, loads on nav click
- ✅ State badge (green = on/open, grey = off)
- ✅ Toggle button per row, reloads list after toggle
- ✅ Graceful messages when no entities or load fails

**Placeholder scan:** None found.

**Type consistency:**
- `list_entities()` returns `list[dict]` with keys `entity_id`, `friendly_name`, `state`, `domain` — endpoint returns same shape directly ✅
- `call_service(base_url, token, domain, service, entity_id)` — called correctly in toggle endpoint ✅
- `toggleHassEntity(btn, entityId)` — `entityId` is a plain string, `encodeURIComponent` handles dots safely ✅
