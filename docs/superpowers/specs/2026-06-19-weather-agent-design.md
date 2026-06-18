# Weather Agent Design

## Goal

Add natural-language weather queries to Plia-OS: current conditions, 7-day forecast, and UV index. A dedicated weather agent parses intent, dispatches to tool functions backed by Open-Meteo (free, no API key required), and returns voice-ready strings.

## Architecture

Full agent pattern (same as wifi/network): `modules/weather_tools.py` provides three `@tool` functions; `agents/weather.py` is a thin LangGraph node that routes to them; `core/supervisor.py` gets keyword routes and graph wiring; `core/config.py` gets a `weather_location` field; `dashboard/static/index.html` gets a city text input in Settings → System.

The existing `get_weather` tool in `modules/web_tools.py` (uses wttr.in) is **removed** and replaced by the new module. All weather surface is owned by the new agent.

## API

**Open-Meteo** — free, no key, stable JSON API.

- Geocoding: `https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json`
- Forecast: `https://api.open-meteo.com/v1/forecast` with query params for lat/lon + desired fields

Timeout: 10 seconds on all HTTP calls. Library: `httpx` (already a dependency).

### Location resolution

```python
def _resolve_location(location: str) -> tuple[float, float, str]:
    """Returns (lat, lon, display_name). Raises ValueError on failure."""
```

1. If `location` is empty, read `get_config().weather_location`.
2. If still empty, raise `ValueError("No location set. Use Settings → System → Weather location or ask 'weather in [city]'.")`.
3. Geocode via Open-Meteo geocoding API. If no results, raise `ValueError(f"Location not found: {location}")`.
4. Return `(latitude, longitude, name)` from the first result.

### WMO weather codes

Map WMO weather interpretation codes to emoji + description inline in `weather_tools.py`:

```python
_WMO_CODES = {
    0: ("☀️", "clear sky"),
    1: ("🌤️", "mainly clear"), 2: ("⛅", "partly cloudy"), 3: ("☁️", "overcast"),
    45: ("🌫️", "fog"), 48: ("🌫️", "icy fog"),
    51: ("🌦️", "light drizzle"), 53: ("🌦️", "drizzle"), 55: ("🌧️", "heavy drizzle"),
    61: ("🌧️", "light rain"), 63: ("🌧️", "rain"), 65: ("🌧️", "heavy rain"),
    71: ("🌨️", "light snow"), 73: ("🌨️", "snow"), 75: ("❄️", "heavy snow"),
    80: ("🌦️", "light showers"), 81: ("🌧️", "showers"), 82: ("⛈️", "violent showers"),
    95: ("⛈️", "thunderstorm"), 96: ("⛈️", "thunderstorm with hail"), 99: ("⛈️", "heavy thunderstorm with hail"),
}

def _wmo(code: int) -> str:
    emoji, desc = _WMO_CODES.get(code, ("🌡️", f"code {code}"))
    return f"{emoji} {desc}"
```

## Components

### `modules/weather_tools.py` (new, ~100 lines)

Three synchronous `@tool` functions. All accept optional `location: str = ""` — if empty, falls back to `get_config().weather_location`.

#### `get_current_weather(location: str = "") -> str`

Open-Meteo params:
```
current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weathercode
```

Returns:
```
Berlin ⛅ partly cloudy · 18°C (feels like 15°C) · 67% humidity · 14 km/h wind
```

Error cases return plain error string (no raise).

#### `get_forecast(location: str = "", days: int = 7) -> str`

Open-Meteo params:
```
daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode
&forecast_days={days}
```

Returns one line per day:
```
7-day forecast for Berlin:
  Mon: ⛅ partly cloudy · 20°C / 11°C · 10% rain
  Tue: 🌧️ rain · 15°C / 9°C · 80% rain
  ...
```

#### `get_uv_index(location: str = "") -> str`

Open-Meteo params:
```
hourly=uv_index&forecast_days=1&timezone=auto
```

Takes the current hour's value. Maps to safety label:

| UV | Label |
|---|---|
| 0–2 | Low |
| 3–5 | Moderate |
| 6–7 | High |
| 8–10 | Very High |
| 11+ | Extreme |

Returns:
```
Berlin UV index: 6 (High) — wear sunscreen
```

### `agents/weather.py` (new, ~60 lines)

LangGraph node. LLM system prompt:

```
You are a weather request parser. Output exactly one JSON object:
{"action": "current|forecast|uv", "location": "<city name or empty string>"}
action: "current" for current conditions, "forecast" for multi-day outlook, "uv" for UV index.
location: city name if specified in the request, empty string to use the configured default.
Output only the JSON object, no other text.
```

Dispatch table:
```python
{"current": get_current_weather, "forecast": get_forecast, "uv": get_uv_index}
```

On JSON parse failure or unknown action: `[weather]\nCouldn't parse that weather request.`
On tool exception: `[weather]\nWeather lookup failed. Please try again.`

Returns `{"tool_results": [..., "[weather]\n<result>"], "active_agent": "weather"}`.

### `core/config.py`

Add after `desktop_notifications`:
```python
    # Weather
    weather_location: str = ""
```

No `_LITERAL_CONSTRAINTS` entry needed (free-form string).

### `core/supervisor.py`

Add to `_KNOWN_INTENTS`:
```python
"weather"
```

Add to `_CLASSIFY_SYSTEM`:
```
Use 'weather' for weather conditions, forecasts, temperature, rain, UV index, or climate queries.
```

Add keyword routes (before "web" entry):
```python
"weather": [
    "weather", "forecast", "temperature outside", "will it rain",
    "is it raining", "rain today", "rain tomorrow", "snow today",
    "how hot", "how cold", "uv index", "sun protection",
    "what's the weather", "how's the weather",
],
```

Add graph node `g.add_node("weather", weather_node)`, conditional edge `"weather": "weather"`, include "weather" in back-edge loop.

### `dashboard/static/index.html`

In Settings → System, after the Notifications block, add:
```html
<hr style="border-color:#222;margin:10px 0;" />
<div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">Weather</div>
<label style="display:block;font-size:0.78rem;color:#999;margin-bottom:4px;">Default location</label>
<input type="text" id="cfg-weather-location" placeholder="e.g. Berlin"
  style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
  onchange="fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({weather_location:this.value.trim()})})">
```

In the config populate block, before `onWebProviderChange()`:
```javascript
      document.getElementById('cfg-weather-location').value = cfg.weather_location || '';
```

## Data Flow

```
user: "will it rain tomorrow in Paris?"
  → supervisor keyword match ("rain tomorrow") → weather node
  → LLM: {"action": "forecast", "location": "Paris"}
  → get_forecast("Paris", 7)
      → _resolve_location("Paris") → geocode → (48.85, 2.35, "Paris")
      → Open-Meteo daily forecast → format 7 lines
      → "7-day forecast for Paris:\n  ..."
  → tool_results → supervisor → respond → TTS
```

```
user: "what's the weather?"
  → config.weather_location = "Berlin" (set by user)
  → LLM: {"action": "current", "location": ""}
  → get_current_weather("") → resolves to "Berlin" → Open-Meteo → formatted string
```

```
user: "what's the weather?"
  → config.weather_location = "" (not set)
  → get_current_weather("") → ValueError → "No location set. Use Settings → System → Weather location or ask 'weather in [city]'."
```

## Error Handling

| Condition | Behaviour |
|---|---|
| `weather_location` empty, no city in query | Returns setup instruction string |
| Geocoding returns no results | Returns `"Location not found: {city}"` |
| HTTP timeout | Returns `"Weather service unavailable (timeout)."` |
| HTTP error status | Returns `"Weather fetch failed: {status}"` |
| JSON parse error on API response | Returns `"Weather data malformed."` |
| Agent LLM returns invalid JSON | Returns `[weather]\nCouldn't parse that weather request.` |

## Tests

### `tests/test_weather_tools.py` (10 tests, mock `httpx.get`)

| Test | Covers |
|---|---|
| `test_current_weather_success` | Full response parsed and formatted correctly |
| `test_current_weather_uses_config_location` | Empty location arg reads from config |
| `test_current_weather_no_location_set` | Config empty + no arg → instruction string |
| `test_current_weather_city_not_found` | Geocoding returns empty results → error string |
| `test_current_weather_http_error` | HTTPError → error string, no raise |
| `test_forecast_success` | 7-day formatted correctly |
| `test_forecast_fewer_days` | days=3 → 3 lines |
| `test_uv_index_success` | UV value + label correct |
| `test_uv_index_categories` | 0→Low, 6→High, 11→Extreme |
| `test_wmo_unknown_code` | Unknown code falls back to `code {n}` |

### `tests/agents/test_weather_agent.py` (5 tests, mock `call_llm` + tools)

| Test | Covers |
|---|---|
| `test_weather_routes_current` | `"current"` action → `get_current_weather` called |
| `test_weather_routes_forecast` | `"forecast"` action → `get_forecast` called |
| `test_weather_routes_uv` | `"uv"` action → `get_uv_index` called |
| `test_weather_invalid_json_fallback` | Malformed LLM output → fallback message |
| `test_weather_location_forwarded` | Location in JSON passed to tool correctly |

## Constraints

- `httpx` only — no `requests`, no `aiohttp`.
- All tool functions synchronous; agent wraps in `asyncio.to_thread`.
- Old `get_weather` in `modules/web_tools.py` removed; all weather surface owned by new module.
- No API key — Open-Meteo only.
- Keyword "weather" must appear before "web" in `_KEYWORD_ROUTES` (dict insertion order).
