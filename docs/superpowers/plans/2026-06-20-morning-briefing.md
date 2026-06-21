# Morning Briefing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `morning_briefing()` tool that compiles weather, reminders, calendar events, and news into a single TTS-friendly digest, triggered on demand by voice or text.

**Architecture:** A single `@tool` in `modules/briefing_tools.py` with four private section helpers — each gathers one data source and degrades silently on failure. The `respond` agent calls it via LLM tool-use; the normal TTS + WebSocket chat flow handles delivery. One new config field (`briefing_news_topic`) and a matching input in Settings → System.

**Tech Stack:** Python 3.12, httpx (already installed), Open-Meteo API (no key), DuckDuckGo news via `duckduckgo_search` (already installed).

## Global Constraints

- All section helpers are synchronous; `morning_briefing()` is called via `asyncio.to_thread` by the registry
- Each section helper is wrapped in its own try/except inside `morning_briefing()`; one failure must not abort others
- Output is plain text — no markdown, no bullet symbols — TTS-friendly
- Import `_resolve_location`, `_wmo`, `_uv_label`, `_FORECAST_URL`, `_TIMEOUT` from `modules.weather_tools` (internal helpers — same codebase)
- Use `list_pending(timers_only=False)` from `MemoryStore` and filter to today's UTC date; do NOT use `get_pending()` (overdue only)
- Calendar events filtered by `dtstart[:10] == today_str` (ISO date prefix)
- News headlines extracted from `fetch_news()` string output — lines starting with `[` that contain `] ` are headline lines
- Test suite: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: Config field

**Files:**
- Modify: `core/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `PliaConfig.briefing_news_topic: str = "world news"` — accessible via `get_config().briefing_news_topic` and settable via `update_config(briefing_news_topic=...)`

- [ ] **Step 1: Write the failing test**

Open `tests/test_config.py`. Add at the end:

```python
def test_briefing_news_topic_default(isolate_config_file):
    from core.config import get_config, update_config
    assert get_config().briefing_news_topic == "world news"
    update_config(briefing_news_topic="technology")
    assert get_config().briefing_news_topic == "technology"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate
pytest tests/test_config.py::test_briefing_news_topic_default -v
```

Expected: FAILED — `AttributeError: 'PliaConfig' object has no attribute 'briefing_news_topic'`

- [ ] **Step 3: Add field to config**

Open `core/config.py`. Find the `@dataclass` block for `PliaConfig`. Find `weather_location: str = ""` and add after it:

```python
    briefing_news_topic: str = "world news"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_config.py::test_briefing_news_topic_default -v
```

Expected: PASSED

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat(briefing): add briefing_news_topic config field"
```

---

### Task 2: `modules/briefing_tools.py`

**Files:**
- Create: `modules/briefing_tools.py`
- Create: `tests/test_briefing_tools.py`

**Interfaces:**
- Consumes: `PliaConfig.briefing_news_topic` (Task 1), `PliaConfig.weather_location` (existing)
- Consumes: `modules.weather_tools._resolve_location(location: str) -> tuple[float, float, str]`
- Consumes: `modules.weather_tools._wmo(code: int) -> str`
- Consumes: `modules.weather_tools._uv_label(uv: float) -> str`
- Consumes: `modules.weather_tools._FORECAST_URL: str`, `modules.weather_tools._TIMEOUT: float`
- Consumes: `agents.memory_store.get_memory_store().list_pending(timers_only=False) -> list[dict]` — each dict has `id`, `message`, `fire_at` (ISO string), `is_timer`
- Consumes: `agents.calendar_store.get_calendar_store().list_events_json() -> list[dict]` — each dict has `uid`, `title`, `dtstart` (ISO string), `dtend`
- Consumes: `modules.news_tools.fetch_news(query: str, max_items: int) -> str`
- Produces: `morning_briefing() -> str` registered via `@tool`

- [ ] **Step 1: Write failing tests**

Create `tests/test_briefing_tools.py`:

```python
from unittest.mock import patch, MagicMock
import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_forecast_response(hi=22.0, lo=14.0, code=1, uv=4.0):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "daily": {
            "temperature_2m_max": [hi],
            "temperature_2m_min": [lo],
            "weathercode": [code],
            "uv_index_max": [uv],
        }
    }
    return resp


def _mock_cfg(topic="world news", location="Berlin"):
    cfg = MagicMock()
    cfg.briefing_news_topic = topic
    cfg.weather_location = location
    return cfg


NEWS_TEXT = (
    "[2026-06-20] AI breakthrough announced — TechNews\n  https://example.com/1\n\n"
    "[2026-06-20] Markets rise on jobs data — Finance Daily\n  https://example.com/2\n\n"
    "[2026-06-20] New climate report released — SciencePost\n  https://example.com/3"
)

REMINDERS = [
    {"id": 1, "message": "take meds", "fire_at": "2026-06-20T09:00:00+00:00", "is_timer": False},
    {"id": 2, "message": "call dentist", "fire_at": "2026-06-20T14:00:00+00:00", "is_timer": False},
    {"id": 3, "message": "timer done", "fire_at": "2026-06-20T08:00:00+00:00", "is_timer": True},
]

CALENDAR_EVENTS = [
    {"uid": "abc123", "title": "Team standup", "dtstart": "2026-06-20T09:30:00", "dtend": "2026-06-20T10:00:00"},
    {"uid": "def456", "title": "Lunch with Alice", "dtstart": "2026-06-20T12:00:00", "dtend": "2026-06-20T13:00:00"},
    {"uid": "ghi789", "title": "Tomorrow's meeting", "dtstart": "2026-06-21T10:00:00", "dtend": "2026-06-21T11:00:00"},
]


# ── test_briefing_all_sections ─────────────────────────────────────────────────

def test_briefing_all_sections():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = REMINDERS
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = CALENDAR_EVENTS

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg()):
        with patch("modules.briefing_tools._resolve_location", return_value=(52.5, 13.4, "Berlin")):
            with patch("httpx.get", return_value=_mock_forecast_response()):
                with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                    with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                        with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT):
                            with patch("modules.briefing_tools.datetime") as mock_dt:
                                mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                                mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                                mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                                result = bt.morning_briefing()

    assert "Weather" in result
    assert "Berlin" in result
    assert "Reminders" in result
    assert "take meds" in result
    assert "call dentist" in result
    assert "timer done" not in result  # timers excluded
    assert "Team standup" in result
    assert "Lunch with Alice" in result
    assert "Tomorrow's meeting" not in result  # different date filtered out
    assert "News" in result
    assert "AI breakthrough" in result


# ── test_briefing_no_reminders ────────────────────────────────────────────────

def test_briefing_no_reminders():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = []

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg()):
        with patch("modules.briefing_tools._resolve_location", return_value=(52.5, 13.4, "Berlin")):
            with patch("httpx.get", return_value=_mock_forecast_response()):
                with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                    with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                        with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT):
                            with patch("modules.briefing_tools.datetime") as mock_dt:
                                mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                                mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                                mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                                result = bt.morning_briefing()

    assert "Reminders" not in result
    assert "Calendar" not in result
    assert "Weather" in result
    assert "News" in result


# ── test_briefing_weather_error ───────────────────────────────────────────────

def test_briefing_weather_error():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = REMINDERS
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = CALENDAR_EVENTS

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg()):
        with patch("modules.briefing_tools._resolve_location", side_effect=ValueError("No location set")):
            with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                    with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT):
                        with patch("modules.briefing_tools.datetime") as mock_dt:
                            mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                            mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                            mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                            result = bt.morning_briefing()

    assert "Weather" not in result
    assert "Reminders" in result
    assert "News" in result


# ── test_briefing_news_uses_config_topic ──────────────────────────────────────

def test_briefing_news_uses_config_topic():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = []

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg(topic="Linux")):
        with patch("modules.briefing_tools._resolve_location", side_effect=ValueError("no loc")):
            with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                    with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT) as mock_news:
                        with patch("modules.briefing_tools.datetime") as mock_dt:
                            mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                            mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                            mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                            bt.morning_briefing()

    mock_news.assert_called_once_with("Linux", max_items=3)


# ── test_briefing_all_fail ────────────────────────────────────────────────────

def test_briefing_all_fail():
    import modules.briefing_tools as bt

    with patch("modules.briefing_tools.get_config", side_effect=Exception("config error")):
        result = bt.morning_briefing()

    assert len(result) > 0  # non-empty fallback


# ── test_briefing_registered_as_tool ─────────────────────────────────────────

def test_briefing_registered_as_tool(reset_registry):
    import modules.briefing_tools  # noqa: F401
    from core.registry import get_tools
    tools = {t["name"] for t in get_tools()}
    assert "morning_briefing" in tools
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_briefing_tools.py -v 2>&1 | head -15
```

Expected: all FAILED with `ModuleNotFoundError: No module named 'modules.briefing_tools'`

- [ ] **Step 3: Create `modules/briefing_tools.py`**

```python
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from agents.calendar_store import get_calendar_store
from agents.memory_store import get_memory_store
from core.config import get_config
from core.registry import tool
from modules.news_tools import fetch_news
from modules.weather_tools import (
    _FORECAST_URL,
    _TIMEOUT,
    _resolve_location,
    _uv_label,
    _wmo,
)

logger = logging.getLogger(__name__)


def _weather_section() -> str:
    cfg = get_config()
    lat, lon, name = _resolve_location(cfg.weather_location)
    resp = httpx.get(
        _FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,weathercode,uv_index_max",
            "forecast_days": 1,
            "timezone": "auto",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    daily = resp.json().get("daily", {})
    hi = daily.get("temperature_2m_max", [None])[0]
    lo = daily.get("temperature_2m_min", [None])[0]
    code = daily.get("weathercode", [0])[0]
    uv = daily.get("uv_index_max", [None])[0]
    uv_str = f", UV {round(uv)} ({_uv_label(round(uv))})" if uv is not None else ""
    return f"Weather: {name} — {_wmo(code)}, high {hi}°C, low {lo}°C{uv_str}."


def _reminders_section() -> str:
    today = datetime.now(timezone.utc).date()
    pending = get_memory_store().list_pending()
    msgs = [
        r["message"]
        for r in pending
        if not r["is_timer"]
        and datetime.fromisoformat(r["fire_at"]).astimezone(timezone.utc).date() == today
    ]
    if not msgs:
        return ""
    return "Reminders today: " + ". ".join(msgs) + "."


def _calendar_section() -> str:
    today_str = datetime.now(timezone.utc).date().isoformat()
    events = get_calendar_store().list_events_json()
    today_events = [e for e in events if e["dtstart"][:10] == today_str]
    if not today_events:
        return ""
    parts = []
    for e in today_events:
        time_part = ""
        if len(e["dtstart"]) > 10:
            try:
                dt = datetime.fromisoformat(e["dtstart"])
                time_part = f" at {dt.strftime('%H:%M')}"
            except ValueError:
                pass
        parts.append(f"{e['title']}{time_part}")
    return "Calendar: " + ". ".join(parts) + "."


def _news_section() -> str:
    cfg = get_config()
    topic = cfg.briefing_news_topic or "world news"
    raw = fetch_news(topic, max_items=3)
    headlines = []
    for line in raw.splitlines():
        if line.startswith("[") and "] " in line:
            rest = line.split("] ", 1)[1]
            title = rest.split(" — ")[0].strip()
            if title:
                headlines.append(title)
    if not headlines:
        return ""
    return f"News — {topic}: " + ". ".join(headlines) + "."


@tool("Get the morning briefing: today's weather, reminders, calendar events, and top news headlines.")
def morning_briefing() -> str:
    sections = []
    for helper in (_weather_section, _reminders_section, _calendar_section, _news_section):
        try:
            section = helper()
            if section:
                sections.append(section)
        except Exception:
            logger.exception("Briefing section %s failed", helper.__name__)

    if not sections:
        return "Morning briefing unavailable right now. Please try again."

    try:
        header = f"Good morning. Briefing for {datetime.now(timezone.utc).strftime('%A, %B %-d')}."
    except Exception:
        header = "Good morning. Here's your briefing."

    return header + "\n\n" + "\n\n".join(sections)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_briefing_tools.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add modules/briefing_tools.py tests/test_briefing_tools.py
git commit -m "feat(briefing): add morning_briefing tool with weather/reminders/calendar/news"
```

---

### Task 3: Supervisor keyword routes

**Files:**
- Modify: `core/supervisor.py`

**Interfaces:**
- Consumes: `_KEYWORD_ROUTES["respond"]` list in `core/supervisor.py`
- Produces: "morning briefing", "daily briefing", etc. route to `respond` agent → LLM calls `morning_briefing()`

- [ ] **Step 1: Add keyword routes**

Open `core/supervisor.py`. Find `_KEYWORD_ROUTES`. Locate the `"respond"` key's list. Add these entries at the end of the list, before the closing `]`:

```python
            "morning briefing", "daily briefing", "today's briefing",
            "give me a briefing", "good morning", "what's today",
            "what's on today", "what do i have today",
```

- [ ] **Step 2: Verify keywords present**

```bash
source .venv/bin/activate
python -c "
from core.supervisor import _KEYWORD_ROUTES
r = _KEYWORD_ROUTES['respond']
checks = ['morning briefing', 'daily briefing', 'good morning', 'what\'s today', 'give me a briefing']
for kw in checks:
    assert kw in r, f'MISSING: {kw}'
print('All briefing keywords present.')
"
```

Expected: `All briefing keywords present.`

- [ ] **Step 3: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add core/supervisor.py
git commit -m "feat(briefing): add morning briefing keyword routes to supervisor"
```

---

### Task 4: Dashboard settings UI

**Files:**
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes: `GET /api/config` → `cfg.briefing_news_topic`
- Consumes: `POST /api/config` with `{briefing_news_topic: string}`

- [ ] **Step 1: Add the HTML input**

Open `dashboard/static/index.html`. Find this block (around line 977):

```html
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Weather</div>
          <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:4px;">Default location</label>
          <input type="text" id="cfg-weather-location" placeholder="e.g. Berlin"
            style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
            onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({weather_location:this.value.trim()})})">
        </div>
```

Replace it with:

```html
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Weather</div>
          <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:4px;">Default location</label>
          <input type="text" id="cfg-weather-location" placeholder="e.g. Berlin"
            style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
            onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({weather_location:this.value.trim()})})">
          <hr style="border-color:#222;margin:10px 0;" />
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Briefing</div>
          <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:4px;">News topic</label>
          <input type="text" id="cfg-briefing-topic" placeholder="e.g. world news"
            style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
            onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({briefing_news_topic:this.value.trim()})})">
        </div>
```

- [ ] **Step 2: Populate on settings load**

Find this line (around line 1611):

```javascript
      document.getElementById('cfg-weather-location').value = cfg.weather_location || '';
```

Add immediately after it:

```javascript
      document.getElementById('cfg-briefing-topic').value = cfg.briefing_news_topic || 'world news';
```

- [ ] **Step 3: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(briefing): add news topic field to Settings > System"
```
