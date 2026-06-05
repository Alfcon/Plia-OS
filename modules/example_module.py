from core.registry import tool


@tool(description="Get the current time in HH:MM format")
def get_time() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    return f"Reminder set: '{message}' in {minutes} minute(s)."
