# Calendar Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the calendar agent stub with a real ICS-backed agent that can add, list, and delete events from a local `~/.plia/calendar.ics` file.

**Architecture:** `agents/calendar_store.py` owns all ICS I/O using the `icalendar` library — add/list/delete operations on a persistent `.ics` file; `agents/calendar.py` is the LangGraph node — it parses the user's intent via `call_llm`, calls the store, and returns formatted results in `tool_results`. Google Calendar is out of scope for this plan (OAuth complexity); the store is designed so a future backend can be dropped in.

**Tech Stack:** icalendar>=5.0 (ICS read/write), Python stdlib (uuid, datetime), LangGraph (existing), call_llm (existing)

---

## File Structure

```
agents/
  calendar_store.py   NEW  — CalendarStore class + get_calendar_store() singleton
  calendar.py         MOD  — replace stub with real LangGraph node

pyproject.toml        MOD  — add icalendar>=5.0 to main deps

tests/agents/
  test_calendar_store.py  NEW  — unit tests for CalendarStore (tmp_path, no side effects)
  test_calendar_node.py   NEW  — unit tests for calendar_node (mocked store)
```

---

### Task 1: agents/calendar_store.py — ICS storage layer

**Files:**
- Modify: `pyproject.toml`
- Create: `agents/calendar_store.py`
- Create: `tests/agents/test_calendar_store.py`

- [ ] **Step 1: Add icalendar to pyproject.toml**

Add `"icalendar>=5.0"` to the main `dependencies` list and install it:

```toml
"icalendar>=5.0",
```

Then:
```bash
/home/alfcon/Projects/Plia-OS/.venv/bin/pip install "icalendar>=5.0" 2>&1 | tail -3
```

- [ ] **Step 2: Write the failing tests**

Create `tests/agents/test_calendar_store.py`:

```python
import pytest
import os
from agents.calendar_store import CalendarStore, reset_calendar_store


@pytest.fixture
def store(tmp_path):
    reset_calendar_store()
    return CalendarStore(ics_path=str(tmp_path / "calendar.ics"))


def test_store_creates_ics_file(tmp_path):
    path = str(tmp_path / "cal.ics")
    CalendarStore(ics_path=path)
    assert os.path.exists(path)


def test_add_event_returns_uid(store):
    uid = store.add_event("Team meeting", "2026-07-01", "10:00", 60)
    assert isinstance(uid, str)
    assert len(uid) > 0


def test_list_events_shows_added_event(store):
    store.add_event("Doctor appointment", "2026-07-02", "14:00", 30)
    events = store.list_events()
    assert any("Doctor appointment" in e for e in events)


def test_list_events_empty_returns_no_events(store):
    events = store.list_events()
    assert events == ["No events found"]


def test_delete_event_removes_it(store):
    uid = store.add_event("To delete", "2026-07-03", "09:00", 15)
    deleted = store.delete_event(uid)
    assert deleted is True
    events = store.list_events()
    assert not any("To delete" in e for e in events)


def test_delete_nonexistent_returns_false(store):
    result = store.delete_event("00000000-0000-0000-0000-000000000000")
    assert result is False


def test_multiple_events_all_listed(store):
    store.add_event("Event A", "2026-07-01", "09:00", 30)
    store.add_event("Event B", "2026-07-02", "10:00", 60)
    events = store.list_events()
    assert len(events) == 2
    assert any("Event A" in e for e in events)
    assert any("Event B" in e for e in events)


def test_event_includes_date_in_listing(store):
    store.add_event("Birthday party", "2026-08-15", "18:00", 120)
    events = store.list_events()
    assert any("2026-08-15" in e for e in events)
```

- [ ] **Step 3: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/agents/test_calendar_store.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'agents.calendar_store'`

- [ ] **Step 4: Create agents/calendar_store.py**

```python
from __future__ import annotations
import logging
import os
import uuid
from datetime import datetime, timedelta

from icalendar import Calendar, Event

logger = logging.getLogger(__name__)


class CalendarStore:
    def __init__(self, ics_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(ics_path)), exist_ok=True)
        self._path = ics_path
        if not os.path.exists(ics_path):
            self._write(self._blank_calendar())

    def _blank_calendar(self) -> Calendar:
        cal = Calendar()
        cal.add("prodid", "-//Plia-OS//Calendar//EN")
        cal.add("version", "2.0")
        return cal

    def _read(self) -> Calendar:
        with open(self._path, "rb") as f:
            return Calendar.from_ical(f.read())

    def _write(self, cal: Calendar) -> None:
        with open(self._path, "wb") as f:
            f.write(cal.to_ical())

    def add_event(
        self,
        title: str,
        date_str: str,
        time_str: str = "09:00",
        duration_min: int = 60,
    ) -> str:
        cal = self._read()
        event = Event()
        uid = str(uuid.uuid4())
        event.add("uid", uid)
        event.add("summary", title)
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        event.add("dtstart", dt)
        event.add("dtend", dt + timedelta(minutes=duration_min))
        event.add("dtstamp", datetime.utcnow())
        cal.add_component(event)
        self._write(cal)
        logger.info("Added event '%s' uid=%s", title, uid[:8])
        return uid

    def list_events(self) -> list[str]:
        cal = self._read()
        results = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("summary", ""))
            uid = str(component.get("uid", ""))
            dtstart = component.get("dtstart")
            if dtstart:
                dt = dtstart.dt
                dt_str = (
                    dt.strftime("%Y-%m-%d %H:%M")
                    if isinstance(dt, datetime)
                    else str(dt)
                )
            else:
                dt_str = "unknown"
            results.append(f"{dt_str}: {summary} (uid: {uid[:8]})")
        return sorted(results) if results else ["No events found"]

    def delete_event(self, uid: str) -> bool:
        cal = self._read()
        new_cal = self._blank_calendar()
        found = False
        for component in cal.walk():
            if component.name == "VEVENT":
                if str(component.get("uid", "")) == uid:
                    found = True
                else:
                    new_cal.add_component(component)
        if found:
            self._write(new_cal)
            logger.info("Deleted event uid=%s", uid[:8])
        return found


_store: CalendarStore | None = None


def get_calendar_store() -> CalendarStore:
    global _store
    if _store is None:
        from core.config import get_config
        config = get_config()
        ics_path = os.path.join(config.memory_dir, "calendar.ics")
        _store = CalendarStore(ics_path)
    return _store


def reset_calendar_store() -> None:
    """Test helper — clears singleton so each test gets a fresh store."""
    global _store
    _store = None
```

- [ ] **Step 5: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_calendar_store.py -v
```

Expected: 8 passed

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥150)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml agents/calendar_store.py tests/agents/test_calendar_store.py
git commit -m "feat: add CalendarStore with ICS add/list/delete operations"
```

---

### Task 2: agents/calendar.py — real LangGraph node

**Files:**
- Modify: `agents/calendar.py`
- Create: `tests/agents/test_calendar_node.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_calendar_node.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.calendar import calendar_node
from agents.calendar_store import reset_calendar_store


@pytest.fixture(autouse=True)
def isolated_store():
    reset_calendar_store()
    with patch("agents.calendar.get_calendar_store") as mock_gcs:
        mock_store = MagicMock()
        mock_store.add_event.return_value = "abc123-uid"
        mock_store.list_events.return_value = ["2026-07-01 10:00: Team meeting (uid: abc123)"]
        mock_store.delete_event.return_value = True
        mock_gcs.return_value = mock_store
        yield mock_store
    reset_calendar_store()


def _state(user_text):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_calendar_node_add_calls_store(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"add","title":"Team meeting","date":"2026-07-01","time":"10:00","duration":60}'}
        update = await calendar_node(_state("add a team meeting on July 1 at 10am"))
    isolated_store.add_event.assert_called_once_with("Team meeting", "2026-07-01", "10:00", 60)
    assert update["active_agent"] == "calendar"
    assert any("Team meeting" in r or "Added" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_calendar_node_list_calls_store(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"list"}'}
        update = await calendar_node(_state("what events do I have"))
    isolated_store.list_events.assert_called_once()
    assert update["active_agent"] == "calendar"
    assert any("Team meeting" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_calendar_node_delete_calls_store(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"delete","uid":"abc123-uid"}'}
        update = await calendar_node(_state("delete event abc123"))
    isolated_store.delete_event.assert_called_once_with("abc123-uid")
    assert update["active_agent"] == "calendar"


@pytest.mark.asyncio
async def test_calendar_node_llm_error_falls_back_to_list(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await calendar_node(_state("show my calendar"))
    isolated_store.list_events.assert_called_once()
    assert update["active_agent"] == "calendar"


@pytest.mark.asyncio
async def test_calendar_node_accumulates_tool_results(isolated_store):
    state = _state("list events")
    state["tool_results"] = ["[memory]\nexisting"]
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"list"}'}
        update = await calendar_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nexisting"
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/agents/test_calendar_node.py -v 2>&1 | head -15
```

Expected: FAIL — stub never calls store methods and returns wrong tool_results.

- [ ] **Step 3: Replace agents/calendar.py**

```python
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.calendar_store import get_calendar_store

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the calendar request. Output JSON with these keys: "
    '"op" ("add", "list", or "delete"), '
    '"title" (event name, for add), '
    '"date" (YYYY-MM-DD, for add), '
    '"time" (HH:MM, for add, default "09:00"), '
    '"duration" (integer minutes, for add, default 60), '
    '"uid" (full uid string, for delete). '
    "Omit keys not relevant to the operation. "
    "Output only valid JSON, no explanation."
)


async def calendar_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = json.loads(msg.get("content", "{}"))
        op = parsed.get("op", "list")
    except Exception:
        op, parsed = "list", {}

    store = get_calendar_store()

    if op == "add":
        title = parsed.get("title", "Untitled")
        date_str = parsed.get("date", "2026-01-01")
        time_str = parsed.get("time", "09:00")
        duration = int(parsed.get("duration", 60))
        uid = store.add_event(title, date_str, time_str, duration)
        result = f"Added event '{title}' on {date_str} at {time_str} (uid: {uid[:8]})"
    elif op == "delete":
        uid = parsed.get("uid", "")
        deleted = store.delete_event(uid)
        result = (
            f"Deleted event {uid[:8]}" if deleted else f"Event {uid[:8] if uid else '?'} not found"
        )
    else:
        events = store.list_events()
        result = "\n".join(events)

    logger.info("Calendar op=%s", op)
    return {
        "tool_results": state["tool_results"] + [f"[calendar]\n{result}"],
        "active_agent": "calendar",
    }
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_calendar_node.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥163)

- [ ] **Step 6: Commit**

```bash
git add agents/calendar.py tests/agents/test_calendar_node.py
git commit -m "feat: implement calendar agent node with add/list/delete via ICS"
```
