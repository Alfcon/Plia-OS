# Voice Pipeline Status Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pipeline status panel to the System sidebar section showing live state (armed/listening/processing/speaking/stopped) with a colored dot and a Start/Stop toggle button.

**Architecture:** A new `core/pipeline_registry.py` module holds the current pipeline task reference and state string, avoiding circular imports between `core/main.py` and `dashboard/server.py`. A new `core/pipeline_runner.py` extracts `_start_pipeline` out of `core/main.py` so both `main.py` and the start endpoint can call it without circularity. Three new API routes handle status/stop/start. The frontend System section (currently empty) is replaced with the panel; the existing WebSocket `status` event already arrives in the browser and is wired to also update the panel dot/label.

**Tech Stack:** FastAPI (existing), asyncio (existing), vanilla JS fetch (existing), `core/events.py` pub/sub (existing)

---

## File Map

| File | Change |
|------|--------|
| `core/pipeline_registry.py` | Create — module-level task ref + state string + get/set helpers |
| `core/pipeline_runner.py` | Create — `start_pipeline()` coroutine (extracted from `core/main.py`) |
| `core/main.py` | Modify — use `start_pipeline()` from runner; store task in registry |
| `dashboard/server.py` | Modify — add `GET /api/pipeline/status`, `POST /api/pipeline/stop`, `POST /api/pipeline/start` |
| `tests/test_pipeline_api.py` | Create — 5 endpoint tests |
| `dashboard/static/index.html` | Modify — replace empty System section with status panel; wire WebSocket + nav btn |

---

### Task 1: Create `core/pipeline_registry.py` and `core/pipeline_runner.py`

**Files:**
- Create: `core/pipeline_registry.py`
- Create: `core/pipeline_runner.py`

No tests in this task — both modules are pure utilities exercised by API tests in Task 3.

- [ ] **Step 1: Create `core/pipeline_registry.py`**

```python
import asyncio

_state: str = "stopped"
_task: "asyncio.Task | None" = None


def get_state() -> str:
    return _state


def set_state(state: str) -> None:
    global _state
    _state = state


def get_task() -> "asyncio.Task | None":
    return _task


def set_task(task: "asyncio.Task | None") -> None:
    global _task
    _task = task
```

- [ ] **Step 2: Create `core/pipeline_runner.py`**

```python
import asyncio
import logging
from core import events
from core import pipeline_registry

logger = logging.getLogger(__name__)


async def _on_pipeline_status(payload: dict) -> None:
    if payload.get("type") == "status":
        pipeline_registry.set_state(payload.get("state", "stopped"))


async def start_pipeline() -> None:
    from voice.pipeline import VoicePipeline
    from core.config import get_config
    config = get_config()
    pipeline = VoicePipeline()
    events.subscribe(pipeline._on_event)
    if _on_pipeline_status not in events._subscribers:
        events.subscribe(_on_pipeline_status)
    try:
        pipeline.load()
        await pipeline.start()
    except Exception:
        logger.exception(
            "Voice pipeline failed to start. "
            "Dashboard and API remain available."
        )
    finally:
        pipeline_registry.set_state("stopped")
```

- [ ] **Step 3: Commit**

```bash
git add core/pipeline_registry.py core/pipeline_runner.py
git commit -m "feat(pipeline): add registry and runner modules for start/stop API support"
```

---

### Task 2: Update `core/main.py` to use registry and runner

**Files:**
- Modify: `core/main.py`

Context: `core/main.py` currently defines `_start_pipeline()` locally (lines 59–72) and starts it as `asyncio.create_task(_start_pipeline())` in the lifespan (line 32). We replace that with `start_pipeline` from the new runner and store the task in the registry.

- [ ] **Step 1: Read current `core/main.py`**

Verify the file matches what's described. Key lines:
- Line 32: `pipeline_task = asyncio.create_task(_start_pipeline())`
- Lines 59–72: `async def _start_pipeline() -> None:` definition

- [ ] **Step 2: Replace `_start_pipeline` usage and delete local definition**

Find this block at the top of `core/main.py` (after existing imports):
```python
from dashboard.server import router as dashboard_router, setup_event_forwarding
```

Replace with:
```python
from dashboard.server import router as dashboard_router, setup_event_forwarding
from core import pipeline_registry
from core.pipeline_runner import start_pipeline
```

Find this line in the lifespan function:
```python
        pipeline_task = asyncio.create_task(_start_pipeline())
```

Replace with:
```python
        pipeline_task = asyncio.create_task(start_pipeline())
        pipeline_registry.set_task(pipeline_task)
```

Find and delete the entire `_start_pipeline` function (lines 59–72):
```python
async def _start_pipeline() -> None:
    from voice.pipeline import VoicePipeline
    from core import events
    config = get_config()
    pipeline = VoicePipeline()
    events.subscribe(pipeline._on_event)  # subscribe before load() so reminders aren't lost during model loading
    try:
        pipeline.load()
        await pipeline.start()
    except Exception:
        logger.exception(
            "Voice pipeline failed to start. "
            "Dashboard and API remain available."
        )

```

Replace with nothing (delete entirely).

Also remove the now-unused `from core.config import get_config` if it's only used in `_start_pipeline` — but `get_config` is also used at line 77 (`cfg = get_config()`), so keep it.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all existing tests pass (pipeline runner is API-equivalent to previous `_start_pipeline`).

- [ ] **Step 4: Commit**

```bash
git add core/main.py
git commit -m "refactor(main): extract pipeline start/stop into pipeline_runner and registry"
```

---

### Task 3: Add pipeline API endpoints and tests

**Files:**
- Modify: `dashboard/server.py`
- Create: `tests/test_pipeline_api.py`

Context: `dashboard/server.py` already imports `asyncio` at line 1. The `core/pipeline_registry` module is safe to import at module level (no circular deps). The `core/pipeline_runner.start_pipeline` must be imported inline inside the endpoint to avoid triggering heavy imports at server startup.

- [ ] **Step 1: Write failing tests**

Create `tests/test_pipeline_api.py`:

```python
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from core.main import create_app
from core import pipeline_registry


@pytest.fixture(autouse=True)
def reset_pipeline_registry():
    pipeline_registry.set_state("stopped")
    pipeline_registry.set_task(None)
    yield
    pipeline_registry.set_state("stopped")
    pipeline_registry.set_task(None)


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_pipeline_status_returns_state(app):
    pipeline_registry.set_state("armed")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/pipeline/status")
    assert r.status_code == 200
    assert r.json() == {"state": "armed"}


@pytest.mark.asyncio
async def test_pipeline_stop_cancels_task(app):
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    pipeline_registry.set_task(mock_task)
    pipeline_registry.set_state("armed")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/stop")
    assert r.status_code == 200
    assert r.json() == {"state": "stopped"}
    mock_task.cancel.assert_called_once()
    assert pipeline_registry.get_state() == "stopped"
    assert pipeline_registry.get_task() is None


@pytest.mark.asyncio
async def test_pipeline_stop_when_no_task_returns_stopped(app):
    pipeline_registry.set_task(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/stop")
    assert r.status_code == 200
    assert r.json() == {"state": "stopped"}


@pytest.mark.asyncio
async def test_pipeline_start_when_already_running_returns_current_state(app):
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    pipeline_registry.set_task(mock_task)
    pipeline_registry.set_state("listening")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/start")
    assert r.status_code == 200
    assert r.json() == {"state": "listening"}


@pytest.mark.asyncio
async def test_pipeline_start_when_stopped_creates_task(app):
    pipeline_registry.set_task(None)
    pipeline_registry.set_state("stopped")
    with patch("core.pipeline_runner.start_pipeline", new=AsyncMock()) as mock_start:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/pipeline/start")
    assert r.status_code == 200
    assert r.json()["state"] == "starting"
    assert pipeline_registry.get_task() is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_pipeline_api.py -v
```

Expected: FAIL — 404 (routes don't exist yet).

- [ ] **Step 3: Add endpoints to `dashboard/server.py`**

At the top of `dashboard/server.py`, after the existing imports, add:
```python
from core import pipeline_registry
```

Find the line:
```python
@router.get("/api/system/info")
```

Insert these three routes immediately before it:

```python
@router.get("/api/pipeline/status")
async def pipeline_status():
    return {"state": pipeline_registry.get_state()}


@router.post("/api/pipeline/stop")
async def pipeline_stop():
    task = pipeline_registry.get_task()
    if task and not task.done():
        task.cancel()
    pipeline_registry.set_state("stopped")
    pipeline_registry.set_task(None)
    return {"state": "stopped"}


@router.post("/api/pipeline/start")
async def pipeline_start():
    task = pipeline_registry.get_task()
    if task and not task.done():
        return {"state": pipeline_registry.get_state()}
    from core.pipeline_runner import start_pipeline
    new_task = asyncio.create_task(start_pipeline())
    pipeline_registry.set_task(new_task)
    pipeline_registry.set_state("starting")
    return {"state": "starting"}


```

- [ ] **Step 4: Run endpoint tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_pipeline_api.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_pipeline_api.py
git commit -m "feat(api): add GET/POST /api/pipeline/status, /stop, /start endpoints"
```

---

### Task 4: Pipeline status panel in System sidebar section

**Files:**
- Modify: `dashboard/static/index.html`

Context:
- `#m-section-system` at line 288 currently contains only an orphaned `#module-list` (`<ul>`) that is never populated (the "System" nav button only calls `showMenuSection('system')`; the actual module list lives in `#m-section-modules`). We replace the orphaned `ul` with the pipeline status panel.
- `#status-badge` (top bar) already shows state from WebSocket `status` events. We add a parallel `_updatePipelineUI(state)` call there to also update the System section panel.
- System nav button at line 102: `onclick="showMenuSection('system')"` — extend to also load status.
- The existing WebSocket handler at the `if (msg.type === 'status')` block already updates `#status-badge`. We add one line there to also call `_updatePipelineUI(msg.state)`.

- [ ] **Step 1: Replace empty System section HTML**

Find this exact block:
```html
        <div id="m-section-system" class="m-pane" style="display:none">
          <ul id="module-list" style="font-size:0.78rem;list-style:none;padding:0;">Loading...</ul>
        </div>
```

Replace with:
```html
        <div id="m-section-system" class="m-pane" style="display:none">
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:10px;">Voice Pipeline</div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="pipeline-state-dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#555;flex-shrink:0;"></span>
              <span id="pipeline-state-label" style="font-size:0.78rem;color:#aaa;">—</span>
            </div>
            <button id="pipeline-toggle-btn" onclick="togglePipeline()"
              style="background:#1e1e1e;border:1px solid #333;border-radius:3px;color:#aaa;font-size:0.75rem;padding:3px 10px;cursor:pointer;">
              Stop
            </button>
          </div>
        </div>
```

- [ ] **Step 2: Update System nav button to load status on open**

Find this exact line:
```html
        <button class="m-nav-btn" data-section="system" onclick="showMenuSection('system')">System</button>
```

Replace with:
```html
        <button class="m-nav-btn" data-section="system" onclick="showMenuSection('system');loadPipelineStatus()">System</button>
```

- [ ] **Step 3: Wire WebSocket `status` event to panel**

Find this exact block in the WebSocket `onmessage` handler:
```javascript
    if (msg.type === 'status') {
      document.getElementById('status-badge').textContent = msg.state;
```

Replace with:
```javascript
    if (msg.type === 'status') {
      document.getElementById('status-badge').textContent = msg.state;
      _updatePipelineUI(msg.state);
```

- [ ] **Step 4: Add JS functions**

Find the `async function downloadHistory()` function. Add the following three functions immediately before it:

```javascript
  function _updatePipelineUI(state) {
    const dot = document.getElementById('pipeline-state-dot');
    const label = document.getElementById('pipeline-state-label');
    const btn = document.getElementById('pipeline-toggle-btn');
    if (!dot) return;
    const colors = {armed:'#81c784', listening:'#4fc3f7', processing:'#ffb74d', speaking:'#ce93d8', stopped:'#555', starting:'#888'};
    dot.style.background = colors[state] || '#555';
    label.textContent = state;
    btn.textContent = (state === 'stopped') ? 'Start' : 'Stop';
    btn.disabled = (state === 'starting');
  }

  async function loadPipelineStatus() {
    try {
      const r = await fetch('/api/pipeline/status');
      if (!r.ok) return;
      const data = await r.json();
      _updatePipelineUI(data.state);
    } catch(e) {}
  }

  async function togglePipeline() {
    const label = document.getElementById('pipeline-state-label');
    const btn = document.getElementById('pipeline-toggle-btn');
    const isStopped = label.textContent === 'stopped' || label.textContent === '—';
    btn.disabled = true;
    try {
      const r = await fetch(isStopped ? '/api/pipeline/start' : '/api/pipeline/stop', {method: 'POST'});
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      _updatePipelineUI(data.state);
    } catch(e) {
      btn.disabled = false;
    }
  }

```

- [ ] **Step 5: Run full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all tests pass (no backend changed in this task).

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add voice pipeline status panel with start/stop to System section"
```

---

## Self-Review

**Spec coverage:**
- ✅ Live state visible in sidebar — colored dot + state label updated via WebSocket `status` events and on section open via `GET /api/pipeline/status`
- ✅ Start/Stop toggle button — `togglePipeline()` calls `/api/pipeline/stop` or `/api/pipeline/start` based on current label
- ✅ `POST /api/pipeline/stop` — cancels task, clears registry, returns `{state:"stopped"}`
- ✅ `POST /api/pipeline/start` — guards against double-start, creates new task, returns `{state:"starting"}`
- ✅ State colors: armed=green, listening=cyan, processing=amber, speaking=purple, stopped=grey, starting=dim grey
- ✅ Button text: "Stop" when running, "Start" when stopped; disabled while "starting"
- ✅ No circular imports: `pipeline_registry` has no outbound imports; `pipeline_runner` imports only from `core.*` and `voice.*`

**Placeholder scan:** None found.

**Type consistency:**
- `pipeline_registry.get_state() -> str` matches `{"state": str}` JSON response ✅
- `asyncio.create_task(start_pipeline())` — `start_pipeline` is an async coroutine ✅
- `_updatePipelineUI(state: str)` called from both WebSocket handler and `loadPipelineStatus()` ✅
- `togglePipeline()` reads `label.textContent === 'stopped'` — matches `pipeline_registry.set_state("stopped")` exact string ✅
