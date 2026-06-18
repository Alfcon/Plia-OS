# Desktop Notifications Design

## Goal

Fire a `notify-send` desktop notification whenever a reminder fires, with a config toggle to enable/disable.

## Architecture

No new agent. A small event subscriber (`core/notifier.py`) hooks into the existing `reminder_fired` event and calls `notify-send`. A single bool field in `PliaConfig` gates the call. A checkbox in Settings → System exposes the toggle.

## Components

### `core/notifier.py` (new, ~25 lines)

Subscribes to the `reminder_fired` event via `events.subscribe`. On each event:
1. Reads `get_config().desktop_notifications`
2. If `False`: returns immediately
3. Calls `subprocess.run(["notify-send", "Plia Reminder", message], timeout=5)`
4. `FileNotFoundError` (notify-send not installed) → `logger.warning`, no raise
5. Any other exception → `logger.exception`, no raise

`setup_notifier()` is the only public function — registers the subscriber and returns.

### `core/config.py`

Add one field to `PliaConfig`:
```python
desktop_notifications: bool = True
```

No `_LITERAL_CONSTRAINTS` entry needed (it's a bool, not a constrained string).

### `core/main.py`

In the lifespan startup block, after `setup_event_forwarding()`, add:
```python
from core.notifier import setup_notifier
setup_notifier()
```

### `dashboard/static/index.html`

In the System settings pane (`id="m-section-system"`), add a checkbox:
```html
<label style="display:flex;align-items:center;gap:8px;font-size:0.78rem;color:#999;margin-bottom:10px;">
  <input type="checkbox" id="cfg-desktop-notifications">
  Desktop notifications for reminders
</label>
```

Wire into `applySystem()` payload:
```javascript
desktop_notifications: document.getElementById('cfg-desktop-notifications').checked,
```

Populate in the `fetch('/api/config').then(cfg => {...})` block:
```javascript
document.getElementById('cfg-desktop-notifications').checked = cfg.desktop_notifications !== false;
```

## Data Flow

```
reminder_loop.py
  → events.emit("reminder_fired", {"id": 156, "message": "take meds"})
  → notifier.py subscriber
      → get_config().desktop_notifications == True?
          yes → subprocess.run(["notify-send", "Plia Reminder", "take meds"])
          no  → return silently
```

## Error Handling

- `notify-send` not installed → `FileNotFoundError` caught, `logger.warning("notify-send not available")`, execution continues
- subprocess non-zero exit → logged at warning level, not raised
- `desktop_notifications = False` → subscriber short-circuits, no subprocess call

## Tests

`tests/test_notifier.py` — 3 tests, mock `subprocess.run` and `get_config`:

| Test | Verifies |
|---|---|
| `test_notification_sent_when_enabled` | `subprocess.run` called with `["notify-send", "Plia Reminder", "take meds"]` when `desktop_notifications=True` |
| `test_notification_skipped_when_disabled` | `subprocess.run` not called when `desktop_notifications=False` |
| `test_notify_send_missing_does_not_raise` | `FileNotFoundError` from subprocess is caught and logged, no exception propagates |

Tests invoke the subscriber function directly (not via event bus) for isolation.

## Constraints

- `notify-send` is the only delivery mechanism — no fallback, no other channels.
- Subscriber is **async** — `emit` in `core/events.py` awaits async callbacks. `subprocess.run` is wrapped in `asyncio.to_thread` to avoid blocking the event loop.
- No new agent, no keyword routes, no LLM involved.
- `desktop_notifications` defaults to `True` — first-run users get notifications without any setup.
