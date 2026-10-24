from core.registry import tool


@tool(description="Add an event to the local calendar. "
      "date must be YYYY-MM-DD, time must be HH:MM (24h), duration in minutes.")
def add_calendar_event(title: str, date: str, time: str = "09:00", duration_minutes: int = 60) -> str:
    from agents.calendar_store import get_calendar_store
    try:
        uid = get_calendar_store().add_event(title, date, time, duration_minutes)
        return f"Event added: '{title}' on {date} at {time} for {duration_minutes} min (id: {uid[:8]})."
    except ValueError as exc:
        return f"Invalid date/time: {exc}"


@tool(description="List all upcoming calendar events.")
def list_calendar_events() -> str:
    from agents.calendar_store import get_calendar_store
    events = get_calendar_store().list_events()
    return "\n".join(events)


@tool(description="Get the next upcoming calendar event.")
def get_next_event() -> str:
    from datetime import datetime, timezone
    from agents.calendar_store import get_calendar_store
    events = get_calendar_store().list_events_json()
    now = datetime.now(timezone.utc).isoformat()
    upcoming = [e for e in events if e["dtstart"] >= now]
    if not upcoming:
        return "No upcoming events."
    e = upcoming[0]
    return f"Next event: '{e['title']}' on {e['dtstart'][:16].replace('T', ' ')} (uid: {e['uid'][:8]})"


@tool(description="Delete a calendar event by its UID prefix (first 8 chars). Use list_calendar_events first.")
def delete_calendar_event(uid: str) -> str:
    from agents.calendar_store import get_calendar_store
    store = get_calendar_store()
    if store.delete_event(uid):
        return f"Event {uid[:8]} deleted."
    return f"No event found with id '{uid}'."
