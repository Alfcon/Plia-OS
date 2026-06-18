# Weather Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add natural-language weather queries (current conditions, 7-day forecast, UV index) via a dedicated agent backed by the Open-Meteo API.

**Architecture:** `modules/weather_tools.py` provides three `@tool` functions; `agents/weather.py` is a thin LangGraph node that parses intent and dispatches to them; `core/supervisor.py` gets keyword routes and graph wiring; `core/config.py` gets a `weather_location` field; `dashboard/static/index.html` gets a location text input. The old `get_weather` (wttr.in) is removed from `modules/web_tools.py`.

**Tech Stack:** Python stdlib + `httpx` (already a dependency), Open-Meteo geocoding and forecast APIs (free, no key), LangGraph (existing).

## Global Constraints

- `httpx` only for HTTP — no `requests`, no `aiohttp`.
- All tool functions are synchronous; agent wraps in `asyncio.to_thread`.
- Old `get_weather` in `modules/web_tools.py` is removed; all weather is owned by new module.
- No API key — Open-Meteo only.
- Keyword `"weather"` entry must appear **before** `"web"` in `_KEYWORD_ROUTES` dict (dict insertion order determines precedence in `_keyword_route()`).
- Test suite: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: Weather tools module + config field + remove old tool

**Files:**
- Create: `modules/weather_tools.py`
- Create: `tests/test_weather_tools.py`
- Modify: `modules/web_tools.py` (remove `get_weather` function)
- Modify: `tests/test_web_tools.py` (remove weather test section)
- Delete: `tests/test_weather_tool.py` (standalone legacy test file)
- Modify: `core/config.py` (add `weather_location` field)

**Interfaces:**
- Produces: `get_current_weather(location: str = "") -> str`
- Produces: `get_forecast(location: str = "", days: int = 7) -> str`
- Produces: `get_uv_index(location: str = "") -> str`
- Produces: `_wmo(code: int) -> str` (module-private helper, tested directly)
- Produces: `_uv_label(uv: float) -> str` (module-private helper, tested directly)
- Produces: `PliaConfig.weather_location: str = ""`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_weather_tools.py`:

```python
import pytest
import httpx
from unittest.mock import patch, MagicMock

_GEO_RESULT = {
    "results": [{"name": "Berlin", "latitude": 52.52, "longitude": 13.41, "country": "Germany"}]
}
_GEO_EMPTY = {"results": []}

_CURRENT_DATA = {
    "current": {
        "temperature_2m": 18.0,
        "apparent_temperature": 15.0,
        "relative_humidity_2m": 67,
        "wind_speed_10m": 14.0,
        "weathercode": 2,
    }
}

_FORECAST_DATA = {
    "daily": {
        "time": ["2026-06-19", "2026-06-20", "2026-06-21"],
        "temperature_2m_max": [20.0, 15.0, 18.0],
        "temperature_2m_min": [11.0, 9.0, 12.0],
        "precipitation_probability_max": [10, 80, 30],
        "weathercode": [2, 63, 1],
    }
}

_UV_DATA = {"hourly": {"uv_index": [6.0] * 24}}


def _mock(json_data):
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = json_data
    return m


def test_current_weather_success():
    from modules.weather_tools import get_current_weather
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_CURRENT_DATA)]):
        result = get_current_weather("Berlin")
    assert "Berlin" in result
    assert "18.0" in result
    assert "⛅" in result or "partly cloudy" in result.lower()


def test_current_weather_uses_config_location():
    from modules.weather_tools import get_current_weather
    mock_cfg = MagicMock()
    mock_cfg.weather_location = "Berlin"
    with patch("modules.weather_tools.get_config", return_value=mock_cfg), \
         patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_CURRENT_DATA)]):
        result = get_current_weather("")
    assert "Berlin" in result


def test_current_weather_no_location_set():
    from modules.weather_tools import get_current_weather
    mock_cfg = MagicMock()
    mock_cfg.weather_location = ""
    with patch("modules.weather_tools.get_config", return_value=mock_cfg):
        result = get_current_weather("")
    assert "Settings" in result or "location" in result.lower()


def test_current_weather_city_not_found():
    from modules.weather_tools import get_current_weather
    with patch("modules.weather_tools.httpx.get", return_value=_mock(_GEO_EMPTY)):
        result = get_current_weather("Atlantis")
    assert "not found" in result.lower()


def test_current_weather_http_error():
    from modules.weather_tools import get_current_weather
    with patch("modules.weather_tools.httpx.get",
               side_effect=httpx.ConnectError("timeout")):
        result = get_current_weather("Berlin")
    assert "unavailable" in result.lower()


def test_forecast_success():
    from modules.weather_tools import get_forecast
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_FORECAST_DATA)]):
        result = get_forecast("Berlin")
    assert "Berlin" in result
    assert "forecast" in result.lower()
    assert "20.0" in result
    assert "°C / " in result


def test_forecast_fewer_days():
    from modules.weather_tools import get_forecast
    data = {
        "daily": {
            "time": ["2026-06-19", "2026-06-20", "2026-06-21"],
            "temperature_2m_max": [20.0, 15.0, 18.0],
            "temperature_2m_min": [11.0, 9.0, 12.0],
            "precipitation_probability_max": [10, 80, 30],
            "weathercode": [2, 63, 1],
        }
    }
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(data)]):
        result = get_forecast("Berlin", days=3)
    day_lines = [l for l in result.splitlines() if "°C / " in l]
    assert len(day_lines) == 3


def test_uv_index_success():
    from modules.weather_tools import get_uv_index
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_UV_DATA)]):
        result = get_uv_index("Berlin")
    assert "Berlin" in result
    assert "6" in result
    assert "High" in result


def test_uv_index_categories():
    from modules.weather_tools import _uv_label
    assert _uv_label(0) == "Low"
    assert _uv_label(2.9) == "Low"
    assert _uv_label(3) == "Moderate"
    assert _uv_label(6) == "High"
    assert _uv_label(8) == "Very High"
    assert _uv_label(11) == "Extreme"


def test_wmo_unknown_code():
    from modules.weather_tools import _wmo
    result = _wmo(999)
    assert "999" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_weather_tools.py --tb=short -q
```

Expected: `ImportError: No module named 'modules.weather_tools'`

- [ ] **Step 3: Remove the old `get_weather` function from `modules/web_tools.py`**

Open `modules/web_tools.py` and delete this block (lines 39–49, including the blank line before `@tool`):

```python


@tool(description="Get current weather for a location. location can be a city name or 'here' for auto-detect.")
def get_weather(location: str = "here") -> str:
    import httpx
    loc = "" if location.lower() in ("here", "my location", "") else location
    url = f"https://wttr.in/{loc}?format=3&m"
    try:
        resp = httpx.get(url, timeout=10.0, headers={"User-Agent": "curl/7.68.0"})
        resp.raise_for_status()
        return resp.text.strip() or "Weather data unavailable."
    except httpx.HTTPError as exc:
        return f"Weather fetch failed: {exc}"
```

The file should end after the `fetch_page` function.

- [ ] **Step 4: Remove weather tests from `tests/test_web_tools.py`**

Open `tests/test_web_tools.py` and delete this block (the `# --- get_weather ---` section at the bottom):

```python


# --- get_weather ---

def test_get_weather_success():
    with patch("httpx.get", return_value=_mock_response(text="London: ⛅ +18°C")):
        from modules.web_tools import get_weather
        result = get_weather("London")
    assert "London" in result
    assert "18" in result


def test_get_weather_here_uses_empty_loc():
    captured = {}
    def fake_get(url, **kwargs):
        captured["url"] = url
        return _mock_response(text="Auto: ☀ +22°C")
    with patch("httpx.get", side_effect=fake_get):
        from modules.web_tools import get_weather
        get_weather("here")
    assert captured["url"].startswith("https://wttr.in/?")


def test_get_weather_http_error():
    with patch("httpx.get", side_effect=httpx.HTTPError("timeout")):
        from modules.web_tools import get_weather
        result = get_weather("Paris")
    assert "failed" in result.lower()
```

- [ ] **Step 5: Delete the standalone legacy test file**

```bash
git rm tests/test_weather_tool.py
```

- [ ] **Step 6: Add `weather_location` to `PliaConfig` in `core/config.py`**

Find this block (after the `desktop_notifications` field):

```python
    # Notifications
    desktop_notifications: bool = True
```

Add after it:

```python
    # Weather
    weather_location: str = ""
```

The block should now read:

```python
    # Notifications
    desktop_notifications: bool = True

    # Weather
    weather_location: str = ""
```

- [ ] **Step 7: Create `modules/weather_tools.py`**

```python
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from core.config import get_config
from core.registry import tool

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 10.0

_WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "clear sky"),
    1: ("🌤️", "mainly clear"), 2: ("⛅", "partly cloudy"), 3: ("☁️", "overcast"),
    45: ("🌫️", "fog"), 48: ("🌫️", "icy fog"),
    51: ("🌦️", "light drizzle"), 53: ("🌦️", "drizzle"), 55: ("🌧️", "heavy drizzle"),
    61: ("🌧️", "light rain"), 63: ("🌧️", "rain"), 65: ("🌧️", "heavy rain"),
    71: ("🌨️", "light snow"), 73: ("🌨️", "snow"), 75: ("❄️", "heavy snow"),
    80: ("🌦️", "light showers"), 81: ("🌧️", "showers"), 82: ("⛈️", "violent showers"),
    95: ("⛈️", "thunderstorm"), 96: ("⛈️", "thunderstorm with hail"),
    99: ("⛈️", "heavy thunderstorm with hail"),
}

_UV_LABELS = [(11, "Extreme"), (8, "Very High"), (6, "High"), (3, "Moderate"), (0, "Low")]


def _wmo(code: int) -> str:
    emoji, desc = _WMO_CODES.get(code, ("🌡️", f"code {code}"))
    return f"{emoji} {desc}"


def _uv_label(uv: float) -> str:
    for threshold, label in _UV_LABELS:
        if uv >= threshold:
            return label
    return "Low"


def _resolve_location(location: str) -> tuple[float, float, str]:
    city = location.strip() or get_config().weather_location.strip()
    if not city:
        raise ValueError(
            "No location set. Use Settings → System → Weather location"
            " or ask 'weather in [city]'."
        )
    resp = httpx.get(
        _GEOCODE_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        raise ValueError(f"Location not found: {city}")
    r = results[0]
    return float(r["latitude"]), float(r["longitude"]), r["name"]


@tool(description="Get current weather conditions for a location. "
      "location can be a city name or empty to use the configured default.")
def get_current_weather(location: str = "") -> str:
    try:
        lat, lon, name = _resolve_location(location)
    except ValueError as exc:
        return str(exc)
    except httpx.HTTPError as exc:
        return f"Weather service unavailable: {exc}"

    try:
        resp = httpx.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,wind_speed_10m,weathercode"
                ),
                "forecast_days": 1,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return f"Weather service unavailable: {exc}"

    c = data.get("current", {})
    temp = c.get("temperature_2m", "?")
    feels = c.get("apparent_temperature", "?")
    humidity = c.get("relative_humidity_2m", "?")
    wind = c.get("wind_speed_10m", "?")
    code = c.get("weathercode", 0)
    return (
        f"{name}: {_wmo(code)} · {temp}°C (feels like {feels}°C)"
        f" · {humidity}% humidity · {wind} km/h wind"
    )


@tool(description="Get a multi-day weather forecast for a location. "
      "location can be a city name or empty to use the configured default. "
      "days controls how many days to show (default 7).")
def get_forecast(location: str = "", days: int = 7) -> str:
    try:
        lat, lon, name = _resolve_location(location)
    except ValueError as exc:
        return str(exc)
    except httpx.HTTPError as exc:
        return f"Weather service unavailable: {exc}"

    try:
        resp = httpx.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,weathercode"
                ),
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return f"Weather service unavailable: {exc}"

    daily = data.get("daily", {})
    times = daily.get("time", [])
    maxs = daily.get("temperature_2m_max", [])
    mins = daily.get("temperature_2m_min", [])
    rains = daily.get("precipitation_probability_max", [])
    codes = daily.get("weathercode", [])

    if not times:
        return "Weather data unavailable."

    lines = [f"7-day forecast for {name}:"]
    for i, date_str in enumerate(times):
        try:
            day_name = datetime.fromisoformat(date_str).strftime("%a")
        except ValueError:
            day_name = date_str
        hi = maxs[i] if i < len(maxs) else "?"
        lo = mins[i] if i < len(mins) else "?"
        rain = rains[i] if i < len(rains) else "?"
        code = codes[i] if i < len(codes) else 0
        lines.append(
            f"  {day_name}: {_wmo(code)} · {hi}°C / {lo}°C · {rain}% rain"
        )
    return "\n".join(lines)


@tool(description="Get the current UV index for a location. "
      "location can be a city name or empty to use the configured default.")
def get_uv_index(location: str = "") -> str:
    try:
        lat, lon, name = _resolve_location(location)
    except ValueError as exc:
        return str(exc)
    except httpx.HTTPError as exc:
        return f"Weather service unavailable: {exc}"

    try:
        resp = httpx.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "uv_index",
                "forecast_days": 1,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return f"Weather service unavailable: {exc}"

    uv_list = data.get("hourly", {}).get("uv_index", [])
    hour = datetime.now(timezone.utc).hour
    if hour >= len(uv_list):
        return "UV data unavailable."
    uv = float(uv_list[hour])
    label = _uv_label(uv)
    advice = " — wear sunscreen" if uv >= 3 else ""
    return f"{name} UV index: {uv:.0f} ({label}){advice}"
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_weather_tools.py --tb=short -q
```

Expected: `10 passed`

- [ ] **Step 9: Run the full test suite to confirm no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all tests pass (old weather tests are gone, new ones in their place).

- [ ] **Step 10: Commit**

```bash
git add modules/weather_tools.py modules/web_tools.py core/config.py \
        tests/test_weather_tools.py tests/test_web_tools.py tests/test_weather_tool.py
git commit -m "feat(weather): add weather tools module with Open-Meteo, remove wttr.in tool"
```

---

### Task 2: Weather agent node

**Files:**
- Create: `agents/weather.py`
- Create: `tests/agents/test_weather_agent.py`

**Interfaces:**
- Consumes: `get_current_weather(location: str) -> str` from `modules.weather_tools`
- Consumes: `get_forecast(location: str, days: int) -> str` from `modules.weather_tools`
- Consumes: `get_uv_index(location: str) -> str` from `modules.weather_tools`
- Consumes: `call_llm(messages) -> dict` and `parse_llm_json(content) -> dict` from `agents.llm`
- Consumes: `AgentState` TypedDict from `core.supervisor` (import under `TYPE_CHECKING`)
- Produces: `weather_node(state: AgentState) -> dict` — async LangGraph node

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_weather_agent.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.weather import weather_node


def _state(user_text: str, prior_results: list | None = None) -> dict:
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": prior_results or [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_invalid_json_returns_fallback():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await weather_node(_state("what's the weather"))
    assert update["active_agent"] == "weather"
    result = "\n".join(update["tool_results"])
    assert "weather" in result.lower()


@pytest.mark.asyncio
async def test_unknown_action_returns_fallback():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"action":"unknown","location":""}'}
        update = await weather_node(_state("what's the weather"))
    assert update["active_agent"] == "weather"
    result = "\n".join(update["tool_results"])
    assert "couldn't parse" in result.lower()


@pytest.mark.asyncio
async def test_action_current_calls_get_current_weather():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_current_weather",
               return_value="Berlin: ⛅ 18°C") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"current","location":"Berlin"}'}
        update = await weather_node(_state("weather in Berlin"))
    mock_fn.assert_called_once_with("Berlin")
    assert update["active_agent"] == "weather"
    assert any(r.startswith("[weather]") for r in update["tool_results"])
    assert "Berlin" in "\n".join(update["tool_results"])


@pytest.mark.asyncio
async def test_action_forecast_calls_get_forecast():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_forecast",
               return_value="7-day forecast for Tokyo:") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"forecast","location":"Tokyo"}'}
        update = await weather_node(_state("forecast for Tokyo"))
    mock_fn.assert_called_once_with("Tokyo")
    assert update["active_agent"] == "weather"


@pytest.mark.asyncio
async def test_action_uv_calls_get_uv_index():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_uv_index",
               return_value="Berlin UV index: 6 (High)") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"uv","location":"Berlin"}'}
        update = await weather_node(_state("uv index in Berlin"))
    mock_fn.assert_called_once_with("Berlin")
    assert update["active_agent"] == "weather"


@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_current_weather", return_value="Berlin: ⛅ 18°C"):
        mock_llm.return_value = {"content": '{"action":"current","location":""}'}
        state = _state("weather")
        state["tool_results"] = ["[memory]\nprior context"]
        update = await weather_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nprior context"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/agents/test_weather_agent.py --tb=short -q
```

Expected: `ImportError: No module named 'agents.weather'`

- [ ] **Step 3: Create `agents/weather.py`**

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from modules.weather_tools import get_current_weather, get_forecast, get_uv_index

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the weather request. "
    'Output JSON with exactly two keys: '
    '"action" (one of: current, forecast, uv), '
    '"location" (city name string, or empty string to use the configured default). '
    "Use 'current' for current conditions or temperature. "
    "Use 'forecast' for multi-day outlook, rain predictions, or future weather. "
    "Use 'uv' for UV index or sun protection queries. "
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[weather]\nCouldn't parse that weather request. "
    "Try: 'weather in Berlin', 'forecast for Tokyo', 'UV index'."
)

_ACTIONS = {"current", "forecast", "uv"}


async def weather_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = parse_llm_json(msg.get("content"))
        action = str(parsed.get("action") or "").strip().lower()
        location = str(parsed.get("location") or "").strip()
        if action not in _ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
    except Exception:
        logger.exception("Weather parse failed for: %r", last_user)
        return {
            "tool_results": state["tool_results"] + [_FALLBACK_MSG],
            "active_agent": "weather",
        }

    try:
        if action == "current":
            result = await asyncio.to_thread(get_current_weather, location)
        elif action == "forecast":
            result = await asyncio.to_thread(get_forecast, location)
        else:  # uv
            result = await asyncio.to_thread(get_uv_index, location)
    except Exception:
        logger.exception("Weather tool failed for action=%r", action)
        result = "Weather lookup failed. Please try again."

    return {
        "tool_results": state["tool_results"] + [f"[weather]\n{result}"],
        "active_agent": "weather",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/agents/test_weather_agent.py --tb=short -q
```

Expected: `6 passed`

- [ ] **Step 5: Run the full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add agents/weather.py tests/agents/test_weather_agent.py
git commit -m "feat(weather): add weather agent node with current/forecast/uv dispatch"
```

---

### Task 3: Supervisor wiring + dashboard location input

**Files:**
- Modify: `core/supervisor.py`
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes: `weather_node(state: AgentState) -> dict` from `agents.weather`
- Consumes: `weather_location: str` from `PliaConfig` via `GET /api/config`
- Produces: `POST /api/config` with `{"weather_location": "..."}` — already handled by existing endpoint

- [ ] **Step 1: Wire `weather_node` into `core/supervisor.py`**

Open `core/supervisor.py`. Make these four edits:

**Edit 1** — add import after the `wifi_node` import (line 19):

Find:
```python
from agents.wifi import wifi_node
from agents.file import file_node
```

Replace with:
```python
from agents.wifi import wifi_node
from agents.file import file_node
from agents.weather import weather_node
```

**Edit 2** — add `"weather"` to `_KNOWN_INTENTS`:

Find:
```python
_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file"}
```

Replace with:
```python
_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file", "weather"}
```

**Edit 3** — update `_CLASSIFY_SYSTEM` to add "weather" to the specialist list and add the routing instruction. Find:

```python
_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder, network, wifi, file. "
    "Use 'reminder' for announcements at a specific future time ('remind me at 3pm', 'notify me in 2 hours'). "
    "Use 'home' only for Home Assistant device control (lights, switches, sensors). "
    "Use 'network' for MAC address operations (show, change, randomize, spoof, restore MAC address). "
    "Use 'wifi' for WiFi status, scanning nearby networks, or listing WiFi interfaces. "
    "Use 'file' for reading, writing, finding, searching, or running files and directories. "
    "Use 'respond' for countdown timers, volume, system info, calculations, or anything answerable with tools directly."
)
```

Replace with:

```python
_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder, network, wifi, file, weather. "
    "Use 'reminder' for announcements at a specific future time ('remind me at 3pm', 'notify me in 2 hours'). "
    "Use 'home' only for Home Assistant device control (lights, switches, sensors). "
    "Use 'network' for MAC address operations (show, change, randomize, spoof, restore MAC address). "
    "Use 'wifi' for WiFi status, scanning nearby networks, or listing WiFi interfaces. "
    "Use 'file' for reading, writing, finding, searching, or running files and directories. "
    "Use 'weather' for weather conditions, forecasts, temperature, rain, UV index, or climate queries. "
    "Use 'respond' for countdown timers, volume, system info, calculations, or anything answerable with tools directly."
)
```

**Edit 4** — add `"weather"` keyword routes **before** the `"web"` entry in `_KEYWORD_ROUTES`. Find:

```python
    "web": ["search for", "search the web", "look it up", "look up", "google ", "find online",
```

Insert before it (preserving indentation):

```python
    "weather": [
        "weather", "forecast", "temperature outside", "will it rain",
        "is it raining", "rain today", "rain tomorrow", "snow today",
        "how hot", "how cold", "uv index", "sun protection",
        "what's the weather", "how's the weather",
    ],
```

**Edit 5** — add `weather_node` to the graph. Find:

```python
    g.add_node("wifi", wifi_node)
    g.add_node("file", file_node)
```

Replace with:

```python
    g.add_node("wifi", wifi_node)
    g.add_node("file", file_node)
    g.add_node("weather", weather_node)
```

**Edit 6** — add `"weather"` to conditional edges. Find:

```python
        "file": "file",
        "respond": "respond",
```

Replace with:

```python
        "file": "file",
        "weather": "weather",
        "respond": "respond",
```

**Edit 7** — add `"weather"` to back-edge loop. Find:

```python
    for agent in ("memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file"):
```

Replace with:

```python
    for agent in ("memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file", "weather"):
```

- [ ] **Step 2: Run the full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 3: Add weather location input to `dashboard/static/index.html`**

Find the closing of the Notifications block (the `</label>` then `</div>` closing `m-section-system`):

```html
          <label style="display:flex;align-items:center;gap:8px;font-size:0.78rem;color:#999;cursor:pointer;">
            <input type="checkbox" id="cfg-desktop-notifications"
              onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({desktop_notifications:this.checked})})">
            Desktop notifications for reminders
          </label>
        </div>
```

Replace with:

```html
          <label style="display:flex;align-items:center;gap:8px;font-size:0.78rem;color:#999;cursor:pointer;">
            <input type="checkbox" id="cfg-desktop-notifications"
              onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({desktop_notifications:this.checked})})">
            Desktop notifications for reminders
          </label>
          <hr style="border-color:#222;margin:10px 0;" />
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Weather</div>
          <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:4px;">Default location</label>
          <input type="text" id="cfg-weather-location" placeholder="e.g. Berlin"
            style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
            onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({weather_location:this.value.trim()})})">
        </div>
```

- [ ] **Step 4: Populate the location input from config on page load**

Find this block in the config fetch callback:

```javascript
      document.getElementById('cfg-desktop-notifications').checked = cfg.desktop_notifications !== false;
      onWebProviderChange();
```

Replace with:

```javascript
      document.getElementById('cfg-desktop-notifications').checked = cfg.desktop_notifications !== false;
      document.getElementById('cfg-weather-location').value = cfg.weather_location || '';
      onWebProviderChange();
```

- [ ] **Step 5: Commit**

```bash
git add core/supervisor.py dashboard/static/index.html
git commit -m "feat(weather): wire weather agent into supervisor, add location input to dashboard"
```
