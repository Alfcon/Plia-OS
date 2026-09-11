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

    c = data.get("current") or {}
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

    daily = data.get("daily") or {}
    times = daily.get("time", [])
    maxs = daily.get("temperature_2m_max", [])
    mins = daily.get("temperature_2m_min", [])
    rains = daily.get("precipitation_probability_max", [])
    codes = daily.get("weathercode", [])

    if not times:
        return "Weather data unavailable."

    lines = [f"{len(times)}-day forecast for {name}:"]
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

    uv_list = (data.get("hourly") or {}).get("uv_index") or []
    hour = datetime.now(timezone.utc).hour
    if hour >= len(uv_list) or uv_list[hour] is None:
        return "UV data unavailable."
    uv = float(uv_list[hour])
    uv_rounded = round(uv)
    label = _uv_label(uv_rounded)
    advice = " — wear sunscreen" if uv_rounded >= 3 else ""
    return f"{name} UV index: {uv_rounded} ({label}){advice}"
