# Calendar Dashboard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Calendar panel to the dashboard with event list, create form, and delete — mirroring the existing Reminders panel pattern.

**Architecture:** `CalendarStore` gains a `list_events_json()` method returning structured dicts. Three REST endpoints (`GET/POST/DELETE /api/calendar`) bridge the dashboard to the store. The Calendar panel in `index.html` follows the exact same HTML/JS pattern as the Reminders panel.

**Tech Stack:** FastAPI (existing), icalendar (existing), vanilla JS + fetch (existing)

---

## File Map

| File | Change |
|------|--------|
| `agents/calendar_store.py` | Add `list_events_json() → list[dict]` |
| `dashboard/server.py` | Add GET/POST/DELETE `/api/calendar` |
| `dashboard/static/index.html` | Add Calendar nav button, panel HTML, JS functions |
| `tests/agents/test_calendar_store.py` | Add `list_events_json` tests |
| `tests/test_calendar_api.py` | New — API endpoint tests |

---

### Task 1: Add `list_events_json()` to CalendarStore

**Files:**
- Modify: `agents/calendar_store.py`
- Modify: `tests/agents/test_calendar_store.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/agents/test_calendar_store.py`:

```python
def test_list_events_json_empty_returns_empty_list(store):
    result = store.list_events_json()
    assert result == []


def test_list_events_json_returns_structured_dicts(store):
    uid = store.add_event("Team lunch", "2026-06-20", "12:00", 60)
    result = store.list_events_json()
    assert len(result) == 1
    assert result[0]["uid"] == uid
    assert result[0]["title"] == "Team lunch"
    assert "2026-06-20" in result[0]["dtstart"]
    assert "dtend" in result[0]


def test_list_events_json_sorted_by_dtstart(store):
    store.add_event("Later", "2026-06-25", "09:00", 60)
    store.add_event("Earlier", "2026-06-20", "09:00", 60)
    result = store.list_events_json()
    assert result[0]["title"] == "Earlier"
    assert result[1]["title"] == "Later"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/agents/test_calendar_store.py::test_list_events_json_empty_returns_empty_list tests/agents/test_calendar_store.py::test_list_events_json_returns_structured_dicts tests/agents/test_calendar_store.py::test_list_events_json_sorted_by_dtstart -v
```

Expected: FAIL with `AttributeError: 'CalendarStore' object has no attribute 'list_events_json'`

- [ ] **Step 3: Implement `list_events_json` in CalendarStore**

In `agents/calendar_store.py`, add after `list_events()` (around line 76):

```python
    def list_events_json(self) -> list[dict]:
        cal = self._read()
        results = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("summary", ""))
            uid = str(component.get("uid", ""))
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")
            start_str = ""
            end_str = ""
            if dtstart:
                dt = dtstart.dt
                start_str = dt.isoformat() if isinstance(dt, datetime) else str(dt)
            if dtend:
                dt = dtend.dt
                end_str = dt.isoformat() if isinstance(dt, datetime) else str(dt)
            results.append({"uid": uid, "title": summary, "dtstart": start_str, "dtend": end_str})
        return sorted(results, key=lambda e: e["dtstart"])
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/agents/test_calendar_store.py -v
```

Expected: all tests PASS (including existing ones)

- [ ] **Step 5: Commit**

```bash
git add agents/calendar_store.py tests/agents/test_calendar_store.py
git commit -m "feat(calendar): add list_events_json returning structured dicts"
```

---

### Task 2: Add Calendar API Endpoints

**Files:**
- Modify: `dashboard/server.py`
- Create: `tests/test_calendar_api.py`

The existing reminder endpoints (lines 248–275 in server.py) are the pattern to follow exactly.

- [ ] **Step 1: Write failing tests**

Create `tests/test_calendar_api.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_list_calendar_events_returns_list(app):
    mock_store = MagicMock()
    mock_store.list_events_json.return_value = [
        {"uid": "abc-123", "title": "Meeting", "dtstart": "2026-06-15T10:00:00", "dtend": "2026-06-15T11:00:00"}
    ]
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/calendar")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["title"] == "Meeting"


@pytest.mark.asyncio
async def test_create_calendar_event_returns_uid(app):
    mock_store = MagicMock()
    mock_store.add_event.return_value = "uid-xyz"
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/calendar", json={
                "title": "Dentist",
                "date": "2026-06-20",
                "time": "14:00",
                "duration_min": 30,
            })
    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == "uid-xyz"
    assert body["title"] == "Dentist"


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_missing_title(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/calendar", json={"date": "2026-06-20"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_missing_date(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/calendar", json={"title": "No date event"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_calendar_event_success(app):
    mock_store = MagicMock()
    mock_store.delete_event.return_value = True
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/calendar/uid-xyz")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert r.json()["uid"] == "uid-xyz"


@pytest.mark.asyncio
async def test_delete_calendar_event_not_found(app):
    mock_store = MagicMock()
    mock_store.delete_event.return_value = False
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete("/api/calendar/no-such-uid")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_calendar_api.py -v
```

Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 3: Add calendar endpoints to `dashboard/server.py`**

Add after the existing `DELETE /api/reminders/{reminder_id}` block (after line 258, before `POST /api/reminders`):

```python
@router.get("/api/calendar")
async def list_calendar_events():
    from agents.calendar_store import get_calendar_store
    return await asyncio.to_thread(get_calendar_store().list_events_json)


@router.post("/api/calendar")
async def create_calendar_event(body: dict):
    title = (body.get("title") or "").strip()
    date = (body.get("date") or "").strip()
    time_str = (body.get("time") or "09:00").strip()
    duration = int(body.get("duration_min") or 60)
    if not title or not date:
        raise HTTPException(status_code=422, detail="title and date required")
    from agents.calendar_store import get_calendar_store
    uid = await asyncio.to_thread(lambda: get_calendar_store().add_event(title, date, time_str, duration))
    return {"uid": uid, "title": title, "date": date, "time": time_str, "duration_min": duration}


@router.delete("/api/calendar/{uid}")
async def delete_calendar_event(uid: str):
    from agents.calendar_store import get_calendar_store
    deleted = await asyncio.to_thread(lambda: get_calendar_store().delete_event(uid))
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"status": "deleted", "uid": uid}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_calendar_api.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py tests/test_calendar_api.py
git commit -m "feat(dashboard): add GET/POST/DELETE /api/calendar endpoints"
```

---

### Task 3: Add Calendar Panel to Dashboard

**Files:**
- Modify: `dashboard/static/index.html`

No backend tests needed — this is pure HTML/JS. Verify manually by running the server.

Pattern reference: the Reminders panel starts at line 250 and runs to line 265. The Calendar panel mirrors this structure.

- [ ] **Step 1: Add Calendar nav button**

In `dashboard/static/index.html`, find the nav button line for `reminders` (line 103):

```html
        <button class="m-nav-btn" data-section="reminders" onclick="showMenuSection('reminders');loadReminders()">Reminders</button>
```

Add a Calendar button immediately after it:

```html
        <button class="m-nav-btn" data-section="calendar" onclick="showMenuSection('calendar');loadCalendar()">Calendar</button>
```

- [ ] **Step 2: Add Calendar panel HTML**

Find the closing `</div>` of the reminders panel (line 265: `</div>`) and add the Calendar panel immediately after it, before `<div id="m-section-home"`:

```html
        <div id="m-section-calendar" class="m-pane" style="display:none">
          <div style="margin-bottom:10px;">
            <span style="font-size:0.78rem;color:#aaa;">New event</span>
            <div style="display:flex;flex-direction:column;gap:5px;margin-top:5px;">
              <input id="cal-title" type="text" placeholder="Event title..." style="background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#e0e0e0;font-size:0.8rem;padding:5px 8px;">
              <input id="cal-date" type="date" style="background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#e0e0e0;font-size:0.8rem;padding:5px 8px;">
              <div style="display:flex;gap:5px;">
                <input id="cal-time" type="time" value="09:00" style="flex:1;background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#e0e0e0;font-size:0.8rem;padding:5px 8px;">
                <input id="cal-duration" type="number" value="60" min="5" placeholder="min" style="width:60px;background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#e0e0e0;font-size:0.8rem;padding:5px 8px;">
              </div>
              <button onclick="createCalendarEvent()" style="background:#2a2a2a;border:1px solid #555;border-radius:4px;color:#a5d6a7;font-size:0.8rem;padding:5px 10px;cursor:pointer;">Add Event</button>
              <span id="cal-status" style="font-size:0.72rem;color:#888;min-height:1em;"></span>
            </div>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
            <span style="font-size:0.78rem;color:#aaa;">Upcoming events</span>
            <button onclick="loadCalendar()" style="background:none;border:none;color:#4fc3f7;font-size:0.75rem;cursor:pointer;">↻ Refresh</button>
          </div>
          <ul id="calendar-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
        </div>
```

- [ ] **Step 3: Add Calendar JS functions**

Find the `createReminder` function in the `<script>` block. Add the following functions directly after it (keep them grouped with other API functions):

```javascript
  async function loadCalendar() {
    const list = document.getElementById('calendar-list');
    list.innerHTML = '<li style="color:#555;font-size:0.75rem;">Loading...</li>';
    try {
      const r = await fetch('/api/calendar');
      const events = await r.json();
      if (!Array.isArray(events) || events.length === 0) {
        list.innerHTML = '<li style="color:#555;font-size:0.75rem;">No upcoming events</li>';
        return;
      }
      list.innerHTML = events.map(ev => {
        const dt = ev.dtstart ? new Date(ev.dtstart).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
        return `<li style="padding:4px 0;border-bottom:1px solid #1a1a1a;display:flex;justify-content:space-between;align-items:center;">
          <span><strong style="color:#e0e0e0;">${_esc(ev.title)}</strong><br><span style="color:#888;">${_esc(dt)}</span></span>
          <button onclick="deleteCalendarEvent('${_esc(ev.uid)}')" style="background:none;border:none;color:#ef9a9a;font-size:0.9rem;cursor:pointer;padding:2px 6px;" title="Delete">✕</button>
        </li>`;
      }).join('');
    } catch(e) {
      list.innerHTML = '<li style="color:#ef9a9a;font-size:0.75rem;">Failed to load events</li>';
    }
  }

  async function createCalendarEvent() {
    const title = document.getElementById('cal-title').value.trim();
    const date = document.getElementById('cal-date').value;
    const time = document.getElementById('cal-time').value || '09:00';
    const duration_min = parseInt(document.getElementById('cal-duration').value) || 60;
    const status = document.getElementById('cal-status');
    status.style.color = '#888';
    status.textContent = '';
    if (!title || !date) { status.textContent = 'Title and date required.'; return; }
    try {
      const r = await fetch('/api/calendar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, date, time, duration_min}),
      });
      if (!r.ok) { const e = await r.json(); status.textContent = e.detail || 'Error'; status.style.color = '#ef9a9a'; return; }
      document.getElementById('cal-title').value = '';
      document.getElementById('cal-date').value = '';
      status.style.color = '#a5d6a7';
      status.textContent = 'Event added.';
      loadCalendar();
    } catch(e) {
      status.style.color = '#ef9a9a';
      status.textContent = 'Network error.';
    }
  }

  async function deleteCalendarEvent(uid) {
    try {
      await fetch('/api/calendar/' + encodeURIComponent(uid), {method: 'DELETE'});
      loadCalendar();
    } catch(e) {}
  }
```

- [ ] **Step 4: Smoke-test in browser**

```bash
source .venv/bin/activate && python -m uvicorn core.main:create_app --factory --port 8000
```

Open `http://localhost:8000`, open the menu (☰), click Settings, then click "Calendar". Verify:
- Panel appears with create form and "No upcoming events" placeholder
- Fill in a title and date, click "Add Event" → event appears in list
- Click ✕ on the event → event disappears
- Click ↻ Refresh → list reloads

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add Calendar panel with event list and create/delete UI"
```
