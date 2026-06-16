from core.registry import tool


@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    from datetime import datetime, timezone, timedelta
    from agents.memory_store import get_memory_store
    fire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    get_memory_store().add_reminder(message, fire_at.isoformat())
    return f"Reminder set: '{message}' in {minutes} minute(s)."


@tool(description="List all pending (not yet fired) reminders with their ID, message, and scheduled time")
def list_pending_reminders() -> str:
    from agents.memory_store import get_memory_store
    reminders = get_memory_store().list_pending()
    if not reminders:
        return "No pending reminders."
    lines = [f"- [{r['id']}] {r['message']} (at {r['fire_at']})" for r in reminders]
    return "\n".join(lines)


@tool(description="Delete a pending reminder by its ID. Use list_pending_reminders first to get the ID.")
def delete_reminder(reminder_id: int) -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    pending = store.list_pending()
    if not any(r["id"] == reminder_id for r in pending):
        return f"No pending reminder with ID {reminder_id}."
    store.mark_reminder_done(reminder_id)
    return f"Reminder {reminder_id} deleted."


@tool(description="Set a countdown timer that announces when it's done. "
      "Specify minutes and/or seconds. Optional label describes what the timer is for.")
def set_timer(minutes: int = 0, seconds: int = 0, label: str = "") -> str:
    from datetime import datetime, timezone, timedelta
    from agents.memory_store import get_memory_store
    total = minutes * 60 + seconds
    if total <= 0:
        return "Specify at least 1 second."
    fire_at = datetime.now(timezone.utc) + timedelta(seconds=total)
    message = f"Timer done{': ' + label if label else ''}!"
    get_memory_store().add_reminder(message, fire_at.isoformat(), is_timer=True)
    parts = []
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    duration = " and ".join(parts)
    return f"Timer set for {duration}{': ' + label if label else ''}."


@tool(description="List all active countdown timers with time remaining.")
def list_timers() -> str:
    from datetime import datetime, timezone
    from agents.memory_store import get_memory_store
    timers = get_memory_store().list_pending(timers_only=True)
    if not timers:
        return "No active timers."
    now = datetime.now(timezone.utc)
    lines = []
    for t in timers:
        fire_at = datetime.fromisoformat(t["fire_at"])
        remaining = max(0, int((fire_at - now).total_seconds()))
        mins, secs = divmod(remaining, 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        lines.append(f"- [{t['id']}] {t['message']} — {time_str} remaining")
    return "\n".join(lines)


@tool(description="Cancel an active timer by label. If no label given, cancels the most recently set timer.")
def cancel_timer(label: str = "") -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    timers = store.list_pending(timers_only=True)
    if not timers:
        return "No active timers."
    if label:
        matches = [t for t in timers if label.lower() in t["message"].lower()]
        if not matches:
            return f"No timer found matching '{label}'."
        target = matches[0]
    else:
        target = max(timers, key=lambda t: t["id"])
    store.mark_reminder_done(target["id"])
    return f"Cancelled: {target['message']}"
