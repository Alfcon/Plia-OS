# Memory Dashboard Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Memory panel to the dashboard that shows all stored facts and lets users delete individual entries.

**Architecture:** Two REST endpoints (`GET/DELETE /api/memory`) bridge the existing `MemoryStore.list_all()` and `MemoryStore.forget()` methods to the dashboard. The Memory panel in `index.html` follows the exact Reminders panel pattern — read-only list + per-row delete, no create form (facts are added via voice/chat).

**Tech Stack:** FastAPI (existing), SQLite via MemoryStore (existing), vanilla JS + fetch (existing)

---

## File Map

| File | Change |
|------|--------|
| `dashboard/server.py` | Add `GET /api/memory` and `DELETE /api/memory/{key}` |
| `dashboard/static/index.html` | Add Memory nav button, panel HTML, JS functions |
| `tests/test_memory_api.py` | New — 4 API endpoint tests |

---

### Task 1: Add Memory API Endpoints

**Files:**
- Modify: `dashboard/server.py`
- Create: `tests/test_memory_api.py`

`MemoryStore` already has:
- `list_all() -> list[dict]` — returns `[{"key": str, "value": str}, ...]` ordered by `updated_at DESC`
- `forget(key: str) -> None` — deletes the fact; no-op if key doesn't exist

Pattern to follow: `GET /api/reminders` and `DELETE /api/reminders/{reminder_id}` (lines 248–258 in `dashboard/server.py`).

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_api.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_memory_returns_facts(app):
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "user_name", "value": "Alice"},
        {"key": "favorite_color", "value": "blue"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/memory")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["key"] == "user_name"
    assert data[0]["value"] == "Alice"


@pytest.mark.asyncio
async def test_list_memory_empty(app):
    mock_store = MagicMock()
    mock_store.list_all.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/memory")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_delete_memory_calls_forget_and_returns_key(app):
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/memory/user_name")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert r.json()["key"] == "user_name"
    mock_store.forget.assert_called_once_with("user_name")


@pytest.mark.asyncio
async def test_delete_memory_nonexistent_key_returns_200(app):
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/memory/no_such_key")
    assert r.status_code == 200
    mock_store.forget.assert_called_once_with("no_such_key")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_memory_api.py -v
```

Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 3: Add endpoints to `dashboard/server.py`**

Read the file to find the `list_reminders` route (around line 248). Add the two memory routes immediately before it:

```python
@router.get("/api/memory")
async def list_memory():
    from agents.memory_store import get_memory_store
    return await asyncio.to_thread(get_memory_store().list_all)


@router.delete("/api/memory/{key}")
async def forget_memory(key: str):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(lambda: get_memory_store().forget(key))
    return {"status": "deleted", "key": key}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_memory_api.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Run full suite for regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_memory_api.py
git commit -m "feat(dashboard): add GET/DELETE /api/memory endpoints"
```

---

### Task 2: Add Memory Panel to Dashboard

**Files:**
- Modify: `dashboard/static/index.html`

No backend tests — pure HTML/JS. Pattern: identical to Reminders panel (read-only list + per-row delete button). No create form.

- [ ] **Step 1: Add Memory nav button**

Find the line with the Home nav button (line 105):
```html
        <button class="m-nav-btn" data-section="home" onclick="showMenuSection('home')">Home</button>
```

Add a Memory button immediately before it:
```html
        <button class="m-nav-btn" data-section="memory" onclick="showMenuSection('memory');loadMemory()">Memory</button>
```

- [ ] **Step 2: Add Memory panel HTML**

Find the opening of the Home panel:
```html
        <div id="m-section-home" class="m-pane" style="display:none">
```

Add the Memory panel immediately before it:
```html
        <div id="m-section-memory" class="m-pane" style="display:none">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
            <span style="font-size:0.78rem;color:#aaa;">Stored memories</span>
            <button onclick="loadMemory()" style="background:none;border:none;color:#4fc3f7;font-size:0.75rem;cursor:pointer;">↻ Refresh</button>
          </div>
          <p style="font-size:0.72rem;color:#555;margin:0 0 8px;">Facts Plia learned from conversation. Say "remember that…" to add.</p>
          <ul id="memory-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
        </div>
```

- [ ] **Step 3: Add Memory JS functions**

Find the `deleteCalendarEvent` function in the `<script>` block. Add the two memory functions immediately after it:

```javascript
  async function loadMemory() {
    const list = document.getElementById('memory-list');
    list.innerHTML = '<li style="color:#555;font-size:0.75rem;">Loading...</li>';
    try {
      const r = await fetch('/api/memory');
      const items = await r.json();
      if (!Array.isArray(items) || items.length === 0) {
        list.innerHTML = '<li style="color:#555;font-size:0.75rem;">No memories stored</li>';
        return;
      }
      list.innerHTML = items.map(m => `<li style="padding:4px 0;border-bottom:1px solid #1a1a1a;display:flex;justify-content:space-between;align-items:flex-start;gap:6px;">
        <span style="word-break:break-word;"><strong style="color:#e0e0e0;">${_esc(m.key)}</strong><br><span style="color:#888;">${_esc(m.value)}</span></span>
        <button onclick="deleteMemory(this.dataset.key)" data-key="${_esc(m.key)}" style="background:none;border:none;color:#ef9a9a;font-size:0.9rem;cursor:pointer;padding:2px 6px;flex-shrink:0;" title="Forget">✕</button>
      </li>`).join('');
    } catch(e) {
      list.innerHTML = '<li style="color:#ef9a9a;font-size:0.75rem;">Failed to load</li>';
    }
  }

  async function deleteMemory(key) {
    try {
      await fetch('/api/memory/' + encodeURIComponent(key), {method: 'DELETE'});
      loadMemory();
    } catch(e) {}
  }
```

- [ ] **Step 4: Smoke-test in browser**

```bash
source .venv/bin/activate && python -m uvicorn core.main:create_app --factory --port 8000
```

1. Open `http://localhost:8000`, open menu (☰), click Settings
2. Click "Memory" nav button — panel appears
3. Say or type something like "remember that my favourite food is sushi"
4. Click ↻ Refresh — entry appears with key and value
5. Click ✕ on entry — it disappears, list reloads

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add Memory panel with stored facts list and delete"
```
