# Google Calendar Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Plia-OS to Google Calendar via OAuth2 so the dashboard Calendar panel reads/writes real Google Calendar events when authorized.

**Architecture:** A new `agents/google_calendar.py` module wraps the Google Calendar API (auth, list, create, delete). Two config fields are added (`gcal_credentials_file`, `gcal_calendar_id`). The existing `GET/POST/DELETE /api/calendar` endpoints (added in the calendar-dashboard-ui plan) transparently route to Google if authorized, local store if not. OAuth flow runs through `/api/calendar/google/auth` → browser popup → `/api/calendar/google/callback` → token saved to `~/.plia/gcal_token.json`. Dashboard Calendar panel gains a "Connect Google Calendar" section that reflects live status.

**Tech Stack:** `google-auth`, `google-auth-oauthlib`, `google-api-python-client` (pip install), FastAPI (existing), vanilla JS (existing)

**Prerequisite:** The calendar-dashboard-ui plan must be implemented first (provides the `/api/calendar` endpoints this plan modifies).

---

## File Map

| File | Change |
|------|--------|
| `agents/google_calendar.py` | New — Google Calendar API wrapper |
| `core/config.py` | Add `gcal_credentials_file`, `gcal_calendar_id` fields |
| `dashboard/server.py` | Add OAuth endpoints; update GET/POST/DELETE /api/calendar to route to Google |
| `dashboard/static/index.html` | Add Google Calendar connect section to Calendar panel |
| `tests/agents/test_google_calendar.py` | New — unit tests for google_calendar module |
| `tests/test_calendar_api.py` | Add tests for OAuth status endpoint and Google-routing behaviour |

---

### Task 1: Install Google Client Libraries

**Files:**
- No code changes — dependency installation

- [ ] **Step 1: Install packages**

```bash
source .venv/bin/activate && pip install google-auth google-auth-oauthlib google-api-python-client
```

- [ ] **Step 2: Verify import works**

```bash
source .venv/bin/activate && python -c "from googleapiclient.discovery import build; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit requirements change if requirements.txt exists**

```bash
source .venv/bin/activate && pip freeze | grep -E "google-auth|google-api" >> requirements.txt && git add requirements.txt && git commit -m "chore: add Google Calendar client libraries" || echo "no requirements.txt, skip"
```

If there is no `requirements.txt`, skip the commit and move on.

---

### Task 2: Add Config Fields for Google Calendar

**Files:**
- Modify: `core/config.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_config_multiagent.py` (the existing config test file):

```python
def test_gcal_credentials_file_default_empty():
    from core.config import PliaConfig
    assert PliaConfig().gcal_credentials_file == ""


def test_gcal_calendar_id_default_primary():
    from core.config import PliaConfig
    assert PliaConfig().gcal_calendar_id == "primary"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_config_multiagent.py::test_gcal_credentials_file_default_empty tests/test_config_multiagent.py::test_gcal_calendar_id_default_primary -v
```

Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add fields to PliaConfig**

In `core/config.py`, find the `# Home automation` block (around line 73) and add after it:

```python
    # Google Calendar
    gcal_credentials_file: str = ""  # path to OAuth 2.0 client_secret.json from Google Cloud Console
    gcal_calendar_id: str = "primary"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_config_multiagent.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config_multiagent.py
git commit -m "feat(config): add gcal_credentials_file and gcal_calendar_id fields"
```

---

### Task 3: Implement `agents/google_calendar.py`

**Files:**
- Create: `agents/google_calendar.py`
- Create: `tests/agents/test_google_calendar.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_google_calendar.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_is_connected_false_when_no_token_file(tmp_path):
    from agents.google_calendar import is_connected
    with patch("agents.google_calendar._token_path", return_value=tmp_path / "gcal_token.json"):
        assert is_connected() is False


def test_list_events_returns_empty_when_not_connected(tmp_path):
    from agents.google_calendar import list_events
    with patch("agents.google_calendar._token_path", return_value=tmp_path / "gcal_token.json"):
        result = list_events()
    assert result == []


def test_list_events_returns_structured_dicts():
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_service = MagicMock()
    mock_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "google-event-1",
                "summary": "Weekly sync",
                "start": {"dateTime": "2026-06-15T10:00:00+00:00"},
                "end": {"dateTime": "2026-06-15T11:00:00+00:00"},
            }
        ]
    }
    with patch("agents.google_calendar.get_credentials", return_value=mock_creds), \
         patch("agents.google_calendar.build", return_value=mock_service):
        from agents.google_calendar import list_events
        result = list_events()
    assert len(result) == 1
    assert result[0]["title"] == "Weekly sync"
    assert result[0]["uid"] == "google-event-1"
    assert result[0]["source"] == "google"
    assert result[0]["dtstart"] == "2026-06-15T10:00:00+00:00"


def test_list_events_handles_all_day_events():
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_service = MagicMock()
    mock_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "allday-1",
                "summary": "Company holiday",
                "start": {"date": "2026-06-20"},
                "end": {"date": "2026-06-21"},
            }
        ]
    }
    with patch("agents.google_calendar.get_credentials", return_value=mock_creds), \
         patch("agents.google_calendar.build", return_value=mock_service):
        from agents.google_calendar import list_events
        result = list_events()
    assert result[0]["dtstart"] == "2026-06-20"


def test_create_event_raises_when_not_connected():
    with patch("agents.google_calendar.get_credentials", return_value=None):
        from agents.google_calendar import create_event
        with pytest.raises(RuntimeError, match="not authorized"):
            create_event("Test", "2026-06-15T10:00:00+00:00", "2026-06-15T11:00:00+00:00")


def test_create_event_calls_api_and_returns_id():
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "new-gcal-id"}
    with patch("agents.google_calendar.get_credentials", return_value=mock_creds), \
         patch("agents.google_calendar.build", return_value=mock_service):
        from agents.google_calendar import create_event
        uid = create_event("Dentist", "2026-06-20T14:00:00+00:00", "2026-06-20T14:30:00+00:00")
    assert uid == "new-gcal-id"


def test_delete_event_raises_when_not_connected():
    with patch("agents.google_calendar.get_credentials", return_value=None):
        from agents.google_calendar import delete_event
        with pytest.raises(RuntimeError, match="not authorized"):
            delete_event("some-uid")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/agents/test_google_calendar.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.google_calendar'`

- [ ] **Step 3: Implement `agents/google_calendar.py`**

Create `agents/google_calendar.py`:

```python
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TOKEN_FILENAME = "gcal_token.json"


def _token_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / _TOKEN_FILENAME


def get_credentials():
    """Return valid Credentials or None if not authorized / not installed."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    path = _token_path()
    if not path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(path), _SCOPES)
    except Exception:
        logger.exception("Failed to load Google Calendar token from %s", path)
        return None
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            path.write_text(creds.to_json())
        except Exception:
            logger.exception("Failed to refresh Google Calendar token")
            return None
    return creds if creds.valid else None


def build_auth_url(credentials_file: str, redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(credentials_file, scopes=_SCOPES, redirect_uri=redirect_uri)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return auth_url


def exchange_code(credentials_file: str, redirect_uri: str, code: str) -> None:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(credentials_file, scopes=_SCOPES, redirect_uri=redirect_uri)
    flow.fetch_token(code=code)
    _token_path().write_text(flow.credentials.to_json())
    logger.info("Google Calendar token saved to %s", _token_path())


def list_events(calendar_id: str = "primary", max_results: int = 20) -> list[dict]:
    creds = get_credentials()
    if creds is None:
        return []
    try:
        from googleapiclient.discovery import build
        from datetime import datetime, timezone
        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc).isoformat()
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        items = result.get("items", [])
        events = []
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            events.append({
                "uid": item.get("id", ""),
                "title": item.get("summary", ""),
                "dtstart": start.get("dateTime") or start.get("date", ""),
                "dtend": end.get("dateTime") or end.get("date", ""),
                "source": "google",
            })
        return events
    except Exception:
        logger.exception("Failed to list Google Calendar events")
        return []


def create_event(title: str, dtstart: str, dtend: str, calendar_id: str = "primary") -> str:
    creds = get_credentials()
    if creds is None:
        raise RuntimeError("Google Calendar not authorized")
    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)
    event_body = {
        "summary": title,
        "start": {"dateTime": dtstart, "timeZone": "UTC"},
        "end": {"dateTime": dtend, "timeZone": "UTC"},
    }
    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return created.get("id", "")


def delete_event(uid: str, calendar_id: str = "primary") -> None:
    creds = get_credentials()
    if creds is None:
        raise RuntimeError("Google Calendar not authorized")
    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)
    service.events().delete(calendarId=calendar_id, eventId=uid).execute()


def is_connected() -> bool:
    return get_credentials() is not None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/agents/test_google_calendar.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/google_calendar.py tests/agents/test_google_calendar.py
git commit -m "feat(calendar): add Google Calendar API wrapper with OAuth2 auth"
```

---

### Task 4: Add OAuth Endpoints and Update Calendar Routing in `dashboard/server.py`

**Files:**
- Modify: `dashboard/server.py`
- Modify: `tests/test_calendar_api.py`

The existing `GET/POST/DELETE /api/calendar` routes from the calendar-dashboard-ui plan get updated to route to Google if `is_connected()` returns True. Three new routes handle OAuth flow.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_calendar_api.py`:

```python
@pytest.mark.asyncio
async def test_google_status_not_connected(app):
    with patch("agents.google_calendar.is_connected", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/calendar/google/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


@pytest.mark.asyncio
async def test_google_status_connected(app):
    with patch("agents.google_calendar.is_connected", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/calendar/google/status")
    assert r.status_code == 200
    assert r.json()["connected"] is True


@pytest.mark.asyncio
async def test_google_auth_requires_credentials_file(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/calendar/google/auth")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_calendar_events_prefers_google_when_connected(app):
    mock_gcal_events = [
        {"uid": "g1", "title": "Google Meeting", "dtstart": "2026-06-15T10:00:00+00:00", "dtend": "2026-06-15T11:00:00+00:00", "source": "google"}
    ]
    with patch("agents.google_calendar.is_connected", return_value=True), \
         patch("agents.google_calendar.list_events", return_value=mock_gcal_events):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/calendar")
    assert r.status_code == 200
    assert r.json()[0]["source"] == "google"


@pytest.mark.asyncio
async def test_create_calendar_event_uses_google_when_connected(app):
    with patch("agents.google_calendar.is_connected", return_value=True), \
         patch("agents.google_calendar.create_event", return_value="gcal-new-id"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/calendar", json={
                "title": "Doctor",
                "date": "2026-06-20",
                "time": "09:00",
                "duration_min": 30,
            })
    assert r.status_code == 200
    assert r.json()["uid"] == "gcal-new-id"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_calendar_api.py::test_google_status_not_connected tests/test_calendar_api.py::test_google_auth_requires_credentials_file tests/test_calendar_api.py::test_list_calendar_events_prefers_google_when_connected -v
```

Expected: FAIL with 404

- [ ] **Step 3: Replace the three calendar routes and add OAuth routes in `dashboard/server.py`**

Find the existing `GET/POST/DELETE /api/calendar` block (three routes added in the calendar-dashboard-ui plan) and replace the entire block:

```python
@router.get("/api/calendar/google/status")
async def google_calendar_status():
    from agents.google_calendar import is_connected
    connected = await asyncio.to_thread(is_connected)
    return {"connected": connected}


@router.post("/api/calendar/google/auth")
async def google_calendar_auth(request: Request):
    from agents.google_calendar import build_auth_url
    config = get_config()
    if not config.gcal_credentials_file:
        raise HTTPException(status_code=422, detail="gcal_credentials_file not configured")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/calendar/google/callback"
    auth_url = await asyncio.to_thread(build_auth_url, config.gcal_credentials_file, redirect_uri)
    return {"auth_url": auth_url}


@router.get("/api/calendar/google/callback")
async def google_calendar_callback(request: Request, code: str = ""):
    from agents.google_calendar import exchange_code
    config = get_config()
    redirect_uri = str(request.base_url).rstrip("/") + "/api/calendar/google/callback"
    await asyncio.to_thread(exchange_code, config.gcal_credentials_file, redirect_uri, code)
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
        "<h2>Google Calendar connected.</h2><p>You can close this tab.</p></body></html>"
    )


@router.get("/api/calendar")
async def list_calendar_events():
    from agents.google_calendar import is_connected, list_events as gcal_list
    if await asyncio.to_thread(is_connected):
        config = get_config()
        return await asyncio.to_thread(gcal_list, config.gcal_calendar_id)
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
    from agents.google_calendar import is_connected, create_event as gcal_create
    if await asyncio.to_thread(is_connected):
        from datetime import datetime, timedelta, timezone
        config = get_config()
        dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        dtend = dt + timedelta(minutes=duration)
        uid = await asyncio.to_thread(gcal_create, title, dt.isoformat(), dtend.isoformat(), config.gcal_calendar_id)
        return {"uid": uid, "title": title, "date": date, "time": time_str, "duration_min": duration}
    from agents.calendar_store import get_calendar_store
    uid = await asyncio.to_thread(lambda: get_calendar_store().add_event(title, date, time_str, duration))
    return {"uid": uid, "title": title, "date": date, "time": time_str, "duration_min": duration}


@router.delete("/api/calendar/{uid}")
async def delete_calendar_event(uid: str):
    from agents.google_calendar import is_connected, delete_event as gcal_delete
    if await asyncio.to_thread(is_connected):
        config = get_config()
        try:
            await asyncio.to_thread(gcal_delete, uid, config.gcal_calendar_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Event not found in Google Calendar")
        return {"status": "deleted", "uid": uid}
    from agents.calendar_store import get_calendar_store
    deleted = await asyncio.to_thread(lambda: get_calendar_store().delete_event(uid))
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"status": "deleted", "uid": uid}
```

Also add `Request` to the FastAPI imports at the top of `dashboard/server.py` if not already present:

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request
```

- [ ] **Step 4: Run all calendar API tests**

```bash
source .venv/bin/activate && pytest tests/test_calendar_api.py -v
```

Expected: all tests PASS (existing 6 + new 5 = 11 total)

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py tests/test_calendar_api.py
git commit -m "feat(dashboard): add Google Calendar OAuth endpoints and route calendar ops through Google when connected"
```

---

### Task 5: Add Google Calendar Connect Section to Dashboard

**Files:**
- Modify: `dashboard/static/index.html`

- [ ] **Step 1: Add Google Calendar section to Calendar panel HTML**

Find the closing `</ul>` of the calendar list in the Calendar panel:

```html
          <ul id="calendar-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
        </div>
```

Replace it with (adds the Google Calendar section below the event list):

```html
          <ul id="calendar-list" style="font-size:0.78rem;list-style:none;padding:0;margin:0;"></ul>
          <div style="margin-top:12px;border-top:1px solid #222;padding-top:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
              <span style="font-size:0.78rem;color:#aaa;">Google Calendar</span>
              <span id="gcal-status-badge" style="font-size:0.72rem;color:#888;">Checking...</span>
            </div>
            <div id="gcal-connect-section" style="display:none">
              <label style="font-size:0.72rem;color:#888;display:block;margin-bottom:2px;">Path to credentials.json (from Google Cloud Console)</label>
              <input id="gcal-creds-file" type="text" placeholder="/home/user/client_secret.json"
                style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#eee;padding:4px 6px;border-radius:3px;font-size:0.75rem;margin-bottom:5px;">
              <button onclick="connectGoogleCalendar()" style="background:#1565c0;border:none;color:#eee;padding:4px 10px;border-radius:3px;font-size:0.75rem;cursor:pointer;width:100%;">Connect Google Calendar</button>
              <div id="gcal-connect-status" style="font-size:0.72rem;margin-top:4px;color:#888;min-height:1em;"></div>
            </div>
          </div>
        </div>
```

- [ ] **Step 2: Add Google Calendar JS functions**

Add after `deleteCalendarEvent` in the `<script>` block:

```javascript
  async function loadGcalStatus() {
    try {
      const r = await fetch('/api/calendar/google/status');
      const data = await r.json();
      const badge = document.getElementById('gcal-status-badge');
      const section = document.getElementById('gcal-connect-section');
      if (data.connected) {
        badge.textContent = '● Connected';
        badge.style.color = '#a5d6a7';
        section.style.display = 'none';
      } else {
        badge.textContent = '○ Not connected';
        badge.style.color = '#ef9a9a';
        section.style.display = '';
      }
    } catch(e) {}
  }

  async function connectGoogleCalendar() {
    const credsFile = document.getElementById('gcal-creds-file').value.trim();
    const statusEl = document.getElementById('gcal-connect-status');
    if (!credsFile) { statusEl.textContent = 'Enter path to credentials.json first.'; return; }
    statusEl.textContent = 'Saving credentials path...';
    await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({gcal_credentials_file: credsFile})});
    statusEl.textContent = 'Opening Google authorization...';
    const r = await fetch('/api/calendar/google/auth', {method:'POST'});
    if (!r.ok) {
      const e = await r.json();
      statusEl.textContent = e.detail || 'Error';
      statusEl.style.color = '#ef9a9a';
      return;
    }
    const data = await r.json();
    window.open(data.auth_url, '_blank', 'width=600,height=700');
    statusEl.textContent = 'Waiting for authorization...';
    const poll = setInterval(async () => {
      try {
        const s = await fetch('/api/calendar/google/status');
        const sd = await s.json();
        if (sd.connected) {
          clearInterval(poll);
          statusEl.textContent = 'Connected!';
          statusEl.style.color = '#a5d6a7';
          loadGcalStatus();
          loadCalendar();
        }
      } catch(e) {}
    }, 2000);
  }
```

- [ ] **Step 3: Call `loadGcalStatus()` when Calendar section opens**

Find the Calendar nav button added in the calendar-dashboard-ui plan:

```html
        <button class="m-nav-btn" data-section="calendar" onclick="showMenuSection('calendar');loadCalendar()">Calendar</button>
```

Update it to also load Google status:

```html
        <button class="m-nav-btn" data-section="calendar" onclick="showMenuSection('calendar');loadCalendar();loadGcalStatus()">Calendar</button>
```

- [ ] **Step 4: Smoke-test OAuth flow end-to-end**

Prerequisites: Download `client_secret_*.json` from Google Cloud Console (OAuth 2.0 Client ID, Desktop app type). Place at a local path.

```bash
source .venv/bin/activate && python -m uvicorn core.main:create_app --factory --port 8000
```

1. Open `http://localhost:8000`, open menu, click Settings → Calendar
2. Google Calendar section shows "○ Not connected"
3. Enter path to `client_secret.json`, click "Connect Google Calendar"
4. Browser popup opens to Google auth page
5. Authorize → popup shows "Google Calendar connected." and closes
6. Dashboard status updates to "● Connected" and event list reloads with Google Calendar events

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add Google Calendar connect section with OAuth status and polling"
```

---

## Self-Review Checklist

- [x] Spec coverage: OAuth initiate, callback, token storage, list/create/delete routing, dashboard connect UI — all covered
- [x] No placeholders: all steps have concrete code
- [x] Type consistency: `list_events()` returns `list[dict]`, `create_event()` returns `str` (uid), `delete_event()` returns `None` — consistent across tasks 3, 4, 5
- [x] Fallback: when Google not connected, all ops fall through to local CalendarStore — tested in Task 4
- [x] `Request` import added to server.py in Task 4 — required for OAuth callback to read `request.base_url`
- [x] `HTMLResponse` already imported in server.py (used by `dashboard()` route) — no new import needed for callback
