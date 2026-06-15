from core.registry import tool


@tool(description="Get the current time in HH:MM format")
def get_time() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


@tool(description="Get the current date including day of week, month, day, and year")
def get_current_date() -> str:
    from datetime import datetime
    return datetime.now().strftime("%A, %B %d, %Y")


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


@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    from datetime import datetime, timezone, timedelta
    from agents.memory_store import get_memory_store
    fire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    get_memory_store().add_reminder(message, fire_at.isoformat())
    return f"Reminder set: '{message}' in {minutes} minute(s)."


@tool(description="Check if a model or application will fit on this system's GPU. "
      "Pass the model name and how much GPU VRAM it requires in gigabytes. "
      "Returns whether it fits and how much VRAM is available. "
      "Uses llmfit for extended LLM queries when installed.")
def check_system_fit(model_name: str, vram_required_gb: float) -> str:
    from core.system_fit import check_custom_fit, query_llmfit
    result = check_custom_fit(model_name, vram_required_gb)
    summary = (
        f"{model_name}: {'✓ fits' if result['fits'] else '✗ does not fit'} — "
        f"requires {vram_required_gb:.1f} GB, {result['vram_available_gb']:.1f} GB available."
    )
    # Try llmfit for additional LLM-specific info (e.g. quantisation advice)
    llmfit_data = query_llmfit(model_name)
    if llmfit_data:
        models = llmfit_data.get("models", [])
        if models:
            top = models[0]
            summary += (
                f" llmfit: best quant {top.get('best_quant', '?')}, "
                f"est. {top.get('estimated_tps', '?')} tok/s, "
                f"fit={top.get('fit_label', '?')}."
            )
    return summary
