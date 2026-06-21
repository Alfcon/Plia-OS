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
    _WMO_CODES,
    _resolve_location,
    _uv_label,
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
    _, desc = _WMO_CODES.get(code, ("", f"condition {code}"))
    return f"Weather: {name} — {desc}, high {hi}°C, low {lo}°C{uv_str}."


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


def _email_section() -> str:
    try:
        from agents.email_store import list_accounts
        from agents.email_client import imap_connection
    except Exception:
        return ""
    accounts = [a for a in list_accounts() if a.get("briefing_enabled")]
    if not accounts:
        return ""
    parts = []
    for acc in accounts:
        try:
            with imap_connection(acc) as conn:
                conn.select("INBOX", readonly=True)
                _, data = conn.search(None, "UNSEEN")
                count = len(data[0].split()) if data[0] else 0
            if count > 0:
                parts.append(f"{acc['name']}: {count} unread")
        except Exception:
            logger.exception("Email briefing section failed for %s", acc.get("name"))
    if not parts:
        return ""
    return "Email: " + ", ".join(parts) + "."


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
    for helper in (_weather_section, _reminders_section, _calendar_section, _email_section, _news_section):
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
