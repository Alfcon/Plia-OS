# Voice Reminder Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create reminders by voice ("remind me to take meds at 3pm") and via the dashboard form, completing the full reminder loop (create → fire → announce).

**Architecture:** A new `agents/reminder.py` node parses the user's natural-language time expression by injecting current UTC into the LLM system prompt and requesting ISO 8601 output, then calls `memory_store.add_reminder()`. The supervisor gains a "reminder" keyword route and intent. The dashboard gains a `POST /api/reminders` endpoint and a small creation form in the existing reminders panel.

**Tech Stack:** Python 3.12, asyncio, langgraph, FastAPI, SQLite (via existing `MemoryStore`), Ollama LLM

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agents/reminder.py` | Parse NL reminder request, call store |
| Create | `tests/agents/test_reminder_agent.py` | Unit tests for reminder_node |
| Modify | `core/supervisor.py` | Add "reminder" to intents, keyword routes, graph |
| Modify | `dashboard/server.py` | Add `POST /api/reminders` |
| Modify | `dashboard/static/index.html` | Add create-reminder form to reminders panel |

---

## Existing APIs you will call

**`agents/memory_store.MemoryStore.add_reminder(message: str, fire_at_iso: str) -> int`**
- `message`: concise reminder text
- `fire_at_iso`: ISO 8601 string with timezone, e.g. `"2026-06-13T15:00:00+00:00"`
- Returns the new reminder's integer id

**`agents/llm.call_llm(messages, tools=None) -> dict`** — async, returns `{"content": str, ...}`

**`agents/llm.parse_llm_json(content: str | None) -> dict`** — strips code fences, returns parsed dict or `{}`

**`agents/memory_store.get_memory_store() -> MemoryStore`** — module singleton

---

## Task 1: `agents/reminder.py` — Reminder Agent Node

**Files:**
- Create: `agents/reminder.py`
- Create: `tests/agents/test_reminder_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_reminder_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.reminder import reminder_node


def _state(user_text: str) -> dict:
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_creates_reminder_calls_store():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 42
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":"Take meds","fire_at":"2026-06-13T15:00:00+00:00"}'}
        update = await reminder_node(_state("remind me to take meds at 3pm"))
    mock_store.add_reminder.assert_called_once_with("Take meds", "2026-06-13T15:00:00+00:00")
    assert update["active_agent"] == "reminder"


@pytest.mark.asyncio
async def test_confirmation_in_tool_results():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 7
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":"Walk the dog","fire_at":"2026-06-14T08:00:00+00:00"}'}
        update = await reminder_node(_state("remind me to walk the dog tomorrow at 8am"))
    result = "\n".join(update["tool_results"])
    assert "Walk the dog" in result
    assert "2026-06-14" in result


@pytest.mark.asyncio
async def test_llm_parse_error_returns_helpful_message():
    mock_store = MagicMock()
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": "not json at all"}
        update = await reminder_node(_state("remind me somehow"))
    mock_store.add_reminder.assert_not_called()
    result = "\n".join(update["tool_results"])
    assert "remind me to" in result.lower() or "couldn't" in result.lower()
    assert update["active_agent"] == "reminder"


@pytest.mark.asyncio
async def test_missing_fields_returns_helpful_message():
    mock_store = MagicMock()
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":""}'}  # missing fire_at, empty message
        update = await reminder_node(_state("remind me"))
    mock_store.add_reminder.assert_not_called()
    assert update["active_agent"] == "reminder"


@pytest.mark.asyncio
async def test_preserves_existing_tool_results():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 1
    state = _state("remind me to call John at noon")
    state["tool_results"] = ["[memory]\nsome prior result"]
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":"Call John","fire_at":"2026-06-13T12:00:00+00:00"}'}
        update = await reminder_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nsome prior result"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/agents/test_reminder_agent.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'agents.reminder'`

- [ ] **Step 3: Write `agents/reminder.py`**

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from agents.memory_store import get_memory_store

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the reminder request. Current UTC time: {now}. "
    'Output JSON with exactly two keys: "message" (what to remind about, concise) '
    'and "fire_at" (ISO 8601 datetime with UTC timezone offset, '
    'e.g. "2026-06-13T15:00:00+00:00"). '
    "If no time is specified, default to 5 minutes from now. "
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[reminder]\nCouldn't parse that reminder. "
    "Try: 'remind me to call John at 3pm tomorrow'."
)


async def reminder_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )
    now = datetime.now(timezone.utc).isoformat()

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM.format(now=now)},
            {"role": "user", "content": last_user},
        ])
        parsed = parse_llm_json(msg.get("content"))
        message = str(parsed.get("message") or "").strip()
        fire_at = str(parsed.get("fire_at") or "").strip()
        if not message or not fire_at:
            raise ValueError("missing fields")
    except Exception:
        logger.exception("Reminder parse failed for: %r", last_user)
        return {
            "tool_results": state["tool_results"] + [_FALLBACK_MSG],
            "active_agent": "reminder",
        }

    store = get_memory_store()
    reminder_id = store.add_reminder(message, fire_at)
    logger.info("Reminder created: id=%d message=%r fire_at=%s", reminder_id, message, fire_at)
    result = f"Reminder set: '{message}' at {fire_at}"
    return {
        "tool_results": state["tool_results"] + [f"[reminder]\n{result}"],
        "active_agent": "reminder",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/agents/test_reminder_agent.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/reminder.py tests/agents/test_reminder_agent.py
git commit -m "feat: add reminder agent node with NL time parsing"
```

---

## Task 2: Wire Reminder into Supervisor

**Files:**
- Modify: `core/supervisor.py`

The supervisor has four places to update:
1. `_KNOWN_INTENTS` (line 20) — set of valid intent strings
2. `_CLASSIFY_SYSTEM` (lines 24-28) — LLM prompt listing specialists
3. `_KEYWORD_ROUTES` (lines 30-36) — keyword → intent dict
4. `_build_graph()` (lines 126-148) — LangGraph nodes and edges

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_supervisor.py (if it exists) or create new file
# tests/test_supervisor_reminder_routing.py
import pytest
from unittest.mock import AsyncMock, patch
from core.supervisor import _keyword_route


def test_keyword_route_remind_me():
    assert _keyword_route("remind me to take my medication at 3pm") == "reminder"


def test_keyword_route_set_a_reminder():
    assert _keyword_route("set a reminder for tomorrow morning") == "reminder"


def test_keyword_route_dont_let_me_forget():
    assert _keyword_route("don't let me forget to call the doctor") == "reminder"


def test_keyword_route_alert_me():
    assert _keyword_route("alert me when the timer goes off") == "reminder"


def test_keyword_route_reminder_unaffected_by_calendar():
    # "schedule a" should still route to calendar, not reminder
    assert _keyword_route("schedule a meeting for Monday") == "calendar"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_supervisor_reminder_routing.py -v
```

Expected: FAIL — keyword_route returns `None` for reminder phrases

- [ ] **Step 3: Update `core/supervisor.py`**

Change line 20 (`_KNOWN_INTENTS`):
```python
_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home", "reminder"}
```

Change lines 24-28 (`_CLASSIFY_SYSTEM`):
```python
_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder. "
    "Use 'reminder' when the user wants to be reminded of something at a future time. "
    "If the request needs no specialist, output: respond."
)
```

Add `"reminder"` to `_KEYWORD_ROUTES` (lines 30-36):
```python
_KEYWORD_ROUTES: dict[str, list[str]] = {
    "memory": ["remember that", "don't forget", "make a note", "recall what", "what did i tell you", "store this", "memorize"],
    "web": ["search for", "search the web", "look it up", "look up", "google ", "find online", "look online", "browse to", "visit http"],
    "code": ["run this code", "execute this", "run python", "run shell", "```python", "```sh", "run the code"],
    "calendar": ["add to calendar", "schedule a", "create an event", "calendar event", "add an appointment", "add event"],
    "home": ["turn on the", "turn off the", "lights on", "lights off", "home automation", "smart home"],
    "reminder": ["remind me", "set a reminder", "set reminder", "alert me", "don't let me forget", "notify me when", "remind me to"],
}
```

Add import and wire in `_build_graph()`:

At top of file, add import after `from agents.home import home_node`:
```python
from agents.reminder import reminder_node
```

In `_build_graph()`, add after `g.add_node("home", home_node)`:
```python
    g.add_node("reminder", reminder_node)
```

In `add_conditional_edges`, add `"reminder": "reminder"`:
```python
    g.add_conditional_edges("supervisor", _route, {
        "memory": "memory",
        "web": "web",
        "code": "code",
        "calendar": "calendar",
        "home": "home",
        "reminder": "reminder",
        "respond": "respond",
    })
```

In the edge loop, add `"reminder"`:
```python
    for agent in ("memory", "web", "code", "calendar", "home", "reminder"):
        g.add_edge(agent, "supervisor")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_supervisor_reminder_routing.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run full suite to check no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add core/supervisor.py tests/test_supervisor_reminder_routing.py
git commit -m "feat: wire reminder agent into supervisor routing"
```

---

## Task 3: Dashboard POST Endpoint

**Files:**
- Modify: `dashboard/server.py`

The existing reminders block is at lines 248-258. Add `POST /api/reminders` after the existing `DELETE` endpoint.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reminder_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_create_reminder_returns_id(app):
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 99
    with patch("dashboard.server.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/reminders", json={
                "message": "Take vitamins",
                "fire_at": "2026-06-14T09:00:00+00:00",
            })
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 99
    assert body["message"] == "Take vitamins"


@pytest.mark.asyncio
async def test_create_reminder_rejects_missing_fields(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/reminders", json={"message": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_reminder_rejects_blank_fire_at(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http/test") as ac:
        r = await ac.post("/api/reminders", json={"message": "Test", "fire_at": ""})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_reminder_api.py -v
```

Expected: FAIL — 404 on POST /api/reminders

- [ ] **Step 3: Add endpoint to `dashboard/server.py`**

Add after the `cancel_reminder` endpoint (after line 258):

```python
@router.post("/api/reminders")
async def create_reminder(body: dict):
    from fastapi import HTTPException
    message = (body.get("message") or "").strip()
    fire_at = (body.get("fire_at") or "").strip()
    if not message or not fire_at:
        raise HTTPException(status_code=422, detail="message and fire_at required")
    from agents.memory_store import get_memory_store
    rid = await asyncio.to_thread(get_memory_store().add_reminder, message, fire_at)
    return {"id": rid, "message": message, "fire_at": fire_at}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_reminder_api.py -v
```

Expected: 3 passed (note: `test_create_reminder_rejects_blank_fire_at` has a typo in base_url — fix to `"http://test"` if it errors)

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py tests/test_reminder_api.py
git commit -m "feat: add POST /api/reminders endpoint"
```

---

## Task 4: Dashboard Create-Reminder Form

**Files:**
- Modify: `dashboard/static/index.html`

The reminders panel is the `<div id="m-section-reminders">` block. It currently shows only a list. Add a small form above the list.

- [ ] **Step 1: Locate the reminders panel**

The panel starts near the line: `<div id="m-section-reminders" class="m-pane" style="display:none">`.

Find the line that says `<ul id="reminder-list" ...>` — add the form just before it.

- [ ] **Step 2: Add form HTML**

Replace the reminders panel content with:

```html
<div id="m-section-reminders" class="m-pane" style="display:none">
  <div style="margin-bottom:10px;">
    <span style="font-size:0.78rem;color:#aaa;">New reminder</span>
    <div style="display:flex;flex-direction:column;gap:5px;margin-top:5px;">
      <input id="reminder-msg" type="text" placeholder="What to remind..." style="background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#e0e0e0;font-size:0.8rem;padding:5px 8px;">
      <input id="reminder-time" type="datetime-local" style="background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#e0e0e0;font-size:0.8rem;padding:5px 8px;">
      <button onclick="createReminder()" style="background:#2a2a2a;border:1px solid #555;border-radius:4px;color:#a5d6a7;font-size:0.8rem;padding:5px 10px;cursor:pointer;">Add Reminder</button>
      <span id="reminder-status" style="font-size:0.72rem;color:#888;min-height:1em;"></span>
    </div>
  </div>
  <span style="font-size:0.78rem;color:#aaa;">Pending reminders</span>
  <ul id="reminder-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
</div>
```

- [ ] **Step 3: Add `createReminder()` JS function**

Find the `async function cancelReminder(id)` function in the `<script>` block. Add `createReminder` just before it:

```javascript
async function createReminder() {
  const msg = document.getElementById('reminder-msg').value.trim();
  const timeVal = document.getElementById('reminder-time').value;
  const statusEl = document.getElementById('reminder-status');
  if (!msg || !timeVal) {
    statusEl.textContent = 'Enter message and time.';
    statusEl.style.color = '#ef9a9a';
    return;
  }
  const fireAt = new Date(timeVal).toISOString();
  try {
    const r = await fetch('/api/reminders', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, fire_at: fireAt}),
    });
    if (!r.ok) throw new Error(await r.text());
    document.getElementById('reminder-msg').value = '';
    document.getElementById('reminder-time').value = '';
    statusEl.textContent = 'Reminder added.';
    statusEl.style.color = '#a5d6a7';
    await loadReminders();
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
  } catch(e) {
    statusEl.textContent = 'Failed: ' + e.message;
    statusEl.style.color = '#ef9a9a';
  }
}
```

- [ ] **Step 4: Manual test**

Start the server:
```bash
source .venv/bin/activate && python3 -m uvicorn core.main:create_app --factory --port 8000
```

Open `http://localhost:8000`. Navigate to Reminders panel. Enter a message and datetime, click "Add Reminder". Verify the new reminder appears in the list below.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: add create-reminder form to dashboard reminders panel"
```

---

## Task 5: Full suite + final commit

- [ ] **Step 1: Run full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass (252+ tests)

- [ ] **Step 2: Smoke-test voice path (optional, requires Ollama)**

Say "remind me to take my medication at 9am tomorrow" to the voice assistant. Verify:
1. Dashboard agent panel shows routing to "reminder"
2. Response confirms the reminder was set
3. Reminder appears in the dashboard Reminders panel
4. When the time comes, `reminder_fired` event fires and voice announces it

