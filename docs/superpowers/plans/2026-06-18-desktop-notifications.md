# Desktop Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fire a `notify-send` desktop notification whenever a reminder fires, with a toggle in Settings → System to enable/disable.

**Architecture:** A small async event subscriber (`core/notifier.py`) hooks into the existing `reminder_fired` event. One bool field (`desktop_notifications: bool = True`) is added to `PliaConfig`. `setup_notifier()` is called in `create_app()` alongside `setup_event_forwarding()`. A checkbox in the System settings pane saves the toggle via `POST /api/config`.

**Tech Stack:** Python stdlib (`subprocess`, `asyncio`), existing `core.events` pub/sub, existing `core.config.PliaConfig`, `dashboard/static/index.html` (vanilla JS).

## Global Constraints

- `notify-send` is the only delivery mechanism — no fallback to other channels.
- Subscriber is async; `subprocess.run` is wrapped in `asyncio.to_thread`.
- `FileNotFoundError` from subprocess must be caught and logged as a warning — never raised.
- `desktop_notifications` defaults to `True` — no user setup required for first run.
- No new agent, no LLM, no keyword routes.
- No automated frontend tests — verify dashboard changes manually.
- Run the full test suite with: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: Notifier, config field, and main.py wiring

**Files:**
- Create: `core/notifier.py`
- Modify: `core/config.py` (add one field after line 90)
- Modify: `core/main.py` (one call after `setup_event_forwarding()`, line 23)
- Create: `tests/test_notifier.py`

**Interfaces:**
- Produces: `setup_notifier() -> None` — called by `core/main.py`
- Produces: `_on_reminder_fired(payload: dict) -> None` — async event subscriber, tested directly

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notifier.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_notification_sent_when_enabled():
    from core.notifier import _on_reminder_fired
    mock_cfg = MagicMock()
    mock_cfg.desktop_notifications = True
    with patch("core.notifier.get_config", return_value=mock_cfg), \
         patch("subprocess.run") as mock_run:
        await _on_reminder_fired({"type": "reminder_fired", "message": "take meds"})
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["notify-send", "Plia Reminder", "take meds"]


@pytest.mark.asyncio
async def test_notification_skipped_when_disabled():
    from core.notifier import _on_reminder_fired
    mock_cfg = MagicMock()
    mock_cfg.desktop_notifications = False
    with patch("core.notifier.get_config", return_value=mock_cfg), \
         patch("subprocess.run") as mock_run:
        await _on_reminder_fired({"type": "reminder_fired", "message": "take meds"})
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_notify_send_missing_does_not_raise():
    from core.notifier import _on_reminder_fired
    mock_cfg = MagicMock()
    mock_cfg.desktop_notifications = True
    with patch("core.notifier.get_config", return_value=mock_cfg), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        await _on_reminder_fired({"type": "reminder_fired", "message": "test"})
    # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_notifier.py --tb=short -q
```

Expected: `ImportError` or `ModuleNotFoundError: No module named 'core.notifier'`

- [ ] **Step 3: Add `desktop_notifications` field to `PliaConfig`**

In `core/config.py`, after line 90 (`tool_permissions: dict = ...`) and before the closing blank line at 91, add:

```python
    # Notifications
    desktop_notifications: bool = True
```

The block should now read:
```python
    # Permissions — maps tool name → "admin" | "user"
    tool_permissions: dict = field(default_factory=dict)

    # Notifications
    desktop_notifications: bool = True
```

- [ ] **Step 4: Create `core/notifier.py`**

```python
from __future__ import annotations
import asyncio
import logging
import subprocess

from core import events
from core.config import get_config

logger = logging.getLogger(__name__)


async def _on_reminder_fired(payload: dict) -> None:
    if payload.get("type") != "reminder_fired":
        return
    if not get_config().desktop_notifications:
        return
    message = payload.get("message", "")
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["notify-send", "Plia Reminder", message],
            timeout=5,
            capture_output=True,
        )
    except FileNotFoundError:
        logger.warning("notify-send not available — desktop notifications disabled")
    except Exception:
        logger.exception("Failed to send desktop notification")


def setup_notifier() -> None:
    events.subscribe(_on_reminder_fired)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_notifier.py --tb=short -q
```

Expected: `3 passed`

- [ ] **Step 6: Wire `setup_notifier()` into `core/main.py`**

In `core/main.py`, the `create_app()` function currently reads (lines 20–23):

```python
    load_modules()
    setup_event_forwarding()
```

Change it to:

```python
    load_modules()
    setup_event_forwarding()
    from core.notifier import setup_notifier
    setup_notifier()
```

- [ ] **Step 7: Run the full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all prior tests pass plus 3 new. Total should be 620+.

- [ ] **Step 8: Commit**

```bash
git add core/notifier.py core/config.py core/main.py tests/test_notifier.py
git commit -m "feat(notifications): fire notify-send on reminder_fired, add desktop_notifications config toggle"
```

---

### Task 2: Dashboard checkbox in Settings → System

**Files:**
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes: `desktop_notifications` bool from `GET /api/config` response
- Consumes: `POST /api/config` with `{"desktop_notifications": bool}` — already handled by existing endpoint

- [ ] **Step 1: Add checkbox HTML to System settings pane**

In `dashboard/static/index.html`, find the System pane closing section. The current end of `id="m-section-system"` (around line 961) reads:

```html
          <div id="config-import-status" style="font-size:0.72rem;color:#888;margin-top:4px;min-height:1em;"></div>
        </div>
```

Insert a new block **before** the closing `</div>` of `m-section-system`:

```html
          <hr style="border-color:#222;margin:10px 0;" />
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Notifications</div>
          <label style="display:flex;align-items:center;gap:8px;font-size:0.78rem;color:#999;cursor:pointer;">
            <input type="checkbox" id="cfg-desktop-notifications"
              onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({desktop_notifications:this.checked})})">
            Desktop notifications for reminders
          </label>
```

The block after the edit should read:

```html
          <div id="config-import-status" style="font-size:0.72rem;color:#888;margin-top:4px;min-height:1em;"></div>
          <hr style="border-color:#222;margin:10px 0;" />
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Notifications</div>
          <label style="display:flex;align-items:center;gap:8px;font-size:0.78rem;color:#999;cursor:pointer;">
            <input type="checkbox" id="cfg-desktop-notifications"
              onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({desktop_notifications:this.checked})})">
            Desktop notifications for reminders
          </label>
        </div>
```

- [ ] **Step 2: Populate checkbox from config on page load**

Find the config populate block (around line 1474), which ends with:

```javascript
      onWebProviderChange();
      onEngineChange();
      startVramPolling();
    });
```

Add one line before `onWebProviderChange()`:

```javascript
      document.getElementById('cfg-desktop-notifications').checked = cfg.desktop_notifications !== false;
      onWebProviderChange();
      onEngineChange();
      startVramPolling();
    });
```

- [ ] **Step 3: Manually verify**

```bash
source .venv/bin/activate && python core/main.py
```

Open `http://localhost:8000`. Verify:
- Settings → System section shows "Notifications" heading with a checkbox
- Checkbox is checked by default (first load with fresh config)
- Uncheck → `POST /api/config` fires in network tab with `{"desktop_notifications": false}`
- Re-check → `POST /api/config` fires with `{"desktop_notifications": true}`
- Reload page → checkbox state persists from saved config

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add desktop notifications toggle to Settings > System"
```
