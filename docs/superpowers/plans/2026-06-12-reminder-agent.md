# Reminder Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `reminders` SQLite table and fake `set_reminder` tool into a working system that persists reminders to the DB and fires them as dashboard notifications via a background polling loop.

**Architecture:** `MemoryStore` gains three reminder CRUD methods (the `reminders` table is already defined in `_init_db()`). The `set_reminder` tool in `modules/example_module.py` is rewritten to persist via those methods. A new `core/reminder_loop.py` module runs an async background task that polls every 30 seconds, emits a `reminder_fired` event for each overdue reminder, and marks it done. The dashboard WebSocket handler displays fired reminders as system messages. The loop is started in `core/main.py` lifespan alongside the voice pipeline task.

**Tech Stack:** Python stdlib (asyncio, datetime), SQLite via existing MemoryStore, existing event bus (core/events.py), existing FastAPI+WebSocket dashboard.

---

## File Structure

```
agents/memory_store.py               MOD — add add_reminder(), get_pending(), mark_reminder_done()
modules/example_module.py            MOD — replace fake set_reminder with real DB-backed version
core/reminder_loop.py                NEW — _check_reminders() + run_reminder_loop() background task
core/main.py                         MOD — start reminder_loop task in lifespan
dashboard/static/index.html          MOD — handle reminder_fired WebSocket event
tests/agents/test_reminder_store.py  NEW — unit tests for three new MemoryStore methods
tests/test_reminder_loop.py          NEW — unit tests for _check_reminders()
tests/test_set_reminder.py           NEW — unit test for wired set_reminder tool
```

---

### Task 1: MemoryStore reminder CRUD methods

**Files:**
- Modify: `agents/memory_store.py`
- Create: `tests/agents/test_reminder_store.py`

**Context you need:**

`agents/memory_store.py` already has this table created in `_init_db()`:
```sql
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    fire_at TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
```
`fire_at` is an ISO-8601 UTC string. `done` is 0 or 1.

The file already imports `from datetime import datetime, timezone` at line 5.

`_conn()` returns `sqlite3.connect(self._db_path)` — use it exactly like the existing `add_turn()` and `recall()` methods.

`reset_memory_store()` is an existing test helper at the bottom of the file that clears the singleton.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_reminder_store.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from agents.memory_store import MemoryStore, reset_memory_store


@pytest.fixture
def store(tmp_path):
    reset_memory_store()
    return MemoryStore(
        db_path=str(tmp_path / "memory.db"),
        chroma_path=str(tmp_path / "chroma"),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_add_reminder_returns_id(store):
    rid = store.add_reminder("Take meds", (_now() + timedelta(minutes=5)).isoformat())
    assert isinstance(rid, int)
    assert rid > 0


def test_get_pending_returns_overdue(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    store.add_reminder("Overdue task", past)
    pending = store.get_pending()
    assert any(r["message"] == "Overdue task" for r in pending)


def test_get_pending_excludes_future(store):
    future = (_now() + timedelta(hours=1)).isoformat()
    store.add_reminder("Future task", future)
    pending = store.get_pending()
    assert not any(r["message"] == "Future task" for r in pending)


def test_get_pending_excludes_done(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    rid = store.add_reminder("Done task", past)
    store.mark_reminder_done(rid)
    pending = store.get_pending()
    assert not any(r["message"] == "Done task" for r in pending)


def test_mark_reminder_done_sets_flag(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    rid = store.add_reminder("Mark me done", past)
    store.mark_reminder_done(rid)
    with store._conn() as conn:
        row = conn.execute("SELECT done FROM reminders WHERE id=?", (rid,)).fetchone()
    assert row[0] == 1


def test_get_pending_returns_id_and_message(store):
    past = (_now() - timedelta(seconds=1)).isoformat()
    store.add_reminder("Check oven", past)
    pending = store.get_pending()
    r = pending[0]
    assert "id" in r and "message" in r
    assert r["message"] == "Check oven"
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/agents/test_reminder_store.py -v 2>&1 | head -15
```

Expected: `AttributeError: 'MemoryStore' object has no attribute 'add_reminder'`

- [ ] **Step 3: Add three methods to MemoryStore**

In `agents/memory_store.py`, add these methods after `clear_history()` (around line 123):

```python
def add_reminder(self, message: str, fire_at_iso: str) -> int:
    with self._conn() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (message, fire_at, done) VALUES (?, ?, 0)",
            (message, fire_at_iso),
        )
        return cur.lastrowid

def get_pending(self) -> list[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT id, message, fire_at FROM reminders WHERE done=0 AND fire_at <= ?",
            (now_iso,),
        ).fetchall()
    return [{"id": r[0], "message": r[1], "fire_at": r[2]} for r in rows]

def mark_reminder_done(self, reminder_id: int) -> None:
    with self._conn() as conn:
        conn.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_reminder_store.py -v
```

Expected: 6 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥172)

- [ ] **Step 6: Commit**

```bash
git add agents/memory_store.py tests/agents/test_reminder_store.py
git commit -m "feat(memory_store): add reminder CRUD — add_reminder, get_pending, mark_reminder_done"
```

---

### Task 2: Wire set_reminder tool to real store

**Files:**
- Modify: `modules/example_module.py`
- Create: `tests/test_set_reminder.py`

**Context you need:**

Current fake implementation in `modules/example_module.py`:
```python
@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    return f"Reminder set: '{message}' in {minutes} minute(s)."
```

The `@tool` decorator from `core/registry.py` registers the function for LLM tool calls. The function must return a string (shown to the LLM as the tool result).

`set_reminder` uses lazy imports inside the function body to avoid circular imports — patch `agents.memory_store.get_memory_store` in tests (not `modules.example_module.get_memory_store`), because the lazy import resolves from `agents.memory_store` at call time.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_set_reminder.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


def test_set_reminder_persists_to_store():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 42
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_reminder
        result = set_reminder("Take meds", 10)
    mock_store.add_reminder.assert_called_once()
    call_args = mock_store.add_reminder.call_args[0]
    assert call_args[0] == "Take meds"
    fire_at = datetime.fromisoformat(call_args[1])
    now = datetime.now(timezone.utc)
    delta = fire_at - now
    assert 9 * 60 < delta.total_seconds() < 11 * 60
    assert "10 minute" in result


def test_set_reminder_returns_confirmation():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 1
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_reminder
        result = set_reminder("Water plants", 30)
    assert "Water plants" in result
    assert "30 minute" in result
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_set_reminder.py -v 2>&1 | head -10
```

Expected: FAIL — `mock_store.add_reminder.assert_called_once()` assertion fails because current stub never calls it.

- [ ] **Step 3: Rewrite set_reminder in example_module.py**

Replace the existing fake `set_reminder` function body (keep the `@tool` decorator):

```python
@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    from datetime import datetime, timezone, timedelta
    from agents.memory_store import get_memory_store
    fire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    get_memory_store().add_reminder(message, fire_at.isoformat())
    return f"Reminder set: '{message}' in {minutes} minute(s)."
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_set_reminder.py -v
```

Expected: 2 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥178)

- [ ] **Step 6: Commit**

```bash
git add modules/example_module.py tests/test_set_reminder.py
git commit -m "feat(reminder): wire set_reminder tool to MemoryStore"
```

---

### Task 3: Polling loop, main.py wiring, dashboard handler

**Files:**
- Create: `core/reminder_loop.py`
- Modify: `core/main.py`
- Modify: `dashboard/static/index.html`
- Create: `tests/test_reminder_loop.py`

**Context you need:**

`core/events.py` exports `async def emit(event_type: str, data: dict)` — broadcasts `{"type": event_type, **data}` to all subscribers. The dashboard WebSocket client is a subscriber and receives every emitted event.

`core/main.py` lifespan currently starts the voice pipeline as a background task:
```python
pipeline_task = asyncio.create_task(_start_pipeline())
yield
pipeline_task.cancel()
try:
    await pipeline_task
except asyncio.CancelledError:
    pass
```
The reminder loop follows the same pattern — create task before `yield`, cancel after.

The dashboard `ws.onmessage` handler is around line 312 of `dashboard/static/index.html`. It already handles `status`, `transcript`, `wake`, `agent_routing`. Add a case for `reminder_fired`.

`core/reminder_loop.py` imports `get_memory_store` at module level so tests can patch `core.reminder_loop.get_memory_store`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reminder_loop.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_check_reminders_fires_overdue():
    mock_store = MagicMock()
    mock_store.get_pending.return_value = [
        {"id": 1, "message": "Water plants", "fire_at": "2026-01-01T00:00:00+00:00"}
    ]
    fired = []

    async def mock_emit(event_type, data):
        fired.append((event_type, data))

    with patch("core.reminder_loop.get_memory_store", return_value=mock_store), \
         patch("core.reminder_loop.events.emit", side_effect=mock_emit):
        from core.reminder_loop import _check_reminders
        await _check_reminders()

    assert len(fired) == 1
    assert fired[0][0] == "reminder_fired"
    assert fired[0][1]["message"] == "Water plants"
    assert fired[0][1]["id"] == 1
    mock_store.mark_reminder_done.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_check_reminders_no_fire_when_empty():
    mock_store = MagicMock()
    mock_store.get_pending.return_value = []
    fired = []

    async def mock_emit(event_type, data):
        fired.append((event_type, data))

    with patch("core.reminder_loop.get_memory_store", return_value=mock_store), \
         patch("core.reminder_loop.events.emit", side_effect=mock_emit):
        from core.reminder_loop import _check_reminders
        await _check_reminders()

    assert fired == []
    mock_store.mark_reminder_done.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_fires_multiple():
    mock_store = MagicMock()
    mock_store.get_pending.return_value = [
        {"id": 1, "message": "First",  "fire_at": "2026-01-01T00:00:00+00:00"},
        {"id": 2, "message": "Second", "fire_at": "2026-01-01T00:00:01+00:00"},
    ]
    fired = []

    async def mock_emit(event_type, data):
        fired.append((event_type, data))

    with patch("core.reminder_loop.get_memory_store", return_value=mock_store), \
         patch("core.reminder_loop.events.emit", side_effect=mock_emit):
        from core.reminder_loop import _check_reminders
        await _check_reminders()

    assert len(fired) == 2
    assert mock_store.mark_reminder_done.call_count == 2
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_reminder_loop.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'core.reminder_loop'`

- [ ] **Step 3: Create core/reminder_loop.py**

```python
from __future__ import annotations
import asyncio
import logging

from core import events
from agents.memory_store import get_memory_store

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 30


async def _check_reminders() -> None:
    store = get_memory_store()
    pending = await asyncio.to_thread(store.get_pending)
    for reminder in pending:
        logger.info("Firing reminder id=%d: %s", reminder["id"], reminder["message"])
        await events.emit("reminder_fired", {"id": reminder["id"], "message": reminder["message"]})
        await asyncio.to_thread(store.mark_reminder_done, reminder["id"])


async def run_reminder_loop() -> None:
    logger.info("Reminder loop started (poll=%ds)", _POLL_INTERVAL_S)
    while True:
        await asyncio.sleep(_POLL_INTERVAL_S)
        try:
            await _check_reminders()
        except Exception:
            logger.exception("Reminder check failed")
```

- [ ] **Step 4: Run reminder loop tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_reminder_loop.py -v
```

Expected: 3 passed

- [ ] **Step 5: Wire loop into core/main.py**

In `core/main.py`, find the lifespan context manager. Replace it with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        import psutil
        psutil.cpu_percent()  # prime baseline; first call always returns 0.0 otherwise
    except ImportError:
        pass
    from core.reminder_loop import run_reminder_loop
    pipeline_task = asyncio.create_task(_start_pipeline())
    reminder_task = asyncio.create_task(run_reminder_loop())
    yield
    pipeline_task.cancel()
    reminder_task.cancel()
    for task in (pipeline_task, reminder_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 6: Add reminder_fired handler to dashboard/static/index.html**

Find the WebSocket `onmessage` handler (around line 328). After the existing `transcript` handler:

```javascript
    if (msg.type === 'transcript') {
      _appendMsg(msg.role, msg.text);
    }
```

Add:

```javascript
    if (msg.type === 'reminder_fired') {
      _appendMsg('system', 'Reminder: ' + msg.message);
    }
```

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥183)

- [ ] **Step 8: Commit**

```bash
git add core/reminder_loop.py core/main.py dashboard/static/index.html tests/test_reminder_loop.py
git commit -m "feat(reminder): polling loop fires overdue reminders as dashboard notifications"
```
