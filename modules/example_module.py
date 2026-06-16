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


@tool(description="Speak a message aloud via the voice pipeline TTS. Use to announce something without waiting for user input.")
def announce(message: str) -> str:
    import asyncio
    from core import events
    asyncio.get_event_loop().create_task(events.emit("speak", {"message": message}))
    return f"Announcing: {message}"


@tool(description="Save a fact to memory with a key and value. Use for user preferences, names, important details to remember long-term.")
def save_memory(key: str, value: str) -> str:
    from agents.memory_store import get_memory_store
    get_memory_store().remember(key, value)
    return f"Remembered: {key} = {value}"


@tool(description="Look up a single stored memory fact by its exact key.")
def get_fact(key: str) -> str:
    from agents.memory_store import get_memory_store
    value = get_memory_store().get_fact(key)
    if value is None:
        return f"No memory found for key '{key}'."
    return f"{key}: {value}"


@tool(description="List all stored memory facts as key-value pairs")
def list_memories() -> str:
    from agents.memory_store import get_memory_store
    facts = get_memory_store().list_all()
    if not facts:
        return "No memories stored."
    lines = [f"- {f['key']}: {f['value']}" for f in facts]
    return "\n".join(lines)


@tool(description="Search stored memories semantically. Use for 'what do you know about X?' or 'what did I tell you about Y?'")
def search_memories(query: str) -> str:
    from agents.memory_store import get_memory_store
    results = get_memory_store().recall(query)
    if not results:
        return "No relevant memories found."
    return "\n".join(results)


@tool(description="Forget a stored memory fact by its exact key. Use list_memories first to get the key.")
def forget_memory(key: str) -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    if store.get_fact(key) is None:
        return f"No memory with key '{key}'."
    store.forget(key)
    return f"Forgotten: '{key}'."


@tool(description="Clear the conversation history and start fresh. Use when asked to 'forget this conversation', 'start over', or 'clear context'.")
def clear_conversation() -> str:
    import asyncio
    from agents.memory_store import get_memory_store
    from core import events
    get_memory_store().clear_history()
    asyncio.get_event_loop().create_task(events.emit("clear_history", {}))
    return "Conversation cleared. Starting fresh."


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
    get_memory_store().add_reminder(message, fire_at.isoformat())
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
    reminders = get_memory_store().list_pending()
    timers = [r for r in reminders if r["message"].startswith("Timer")]
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
    timers = [r for r in store.list_pending() if r["message"].startswith("Timer")]
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


@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    from datetime import datetime, timezone, timedelta
    from agents.memory_store import get_memory_store
    fire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    get_memory_store().add_reminder(message, fire_at.isoformat())
    return f"Reminder set: '{message}' in {minutes} minute(s)."


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


@tool(description="Delete a calendar event by its UID prefix (first 8 chars). Use list_calendar_events first.")
def delete_calendar_event(uid: str) -> str:
    from agents.calendar_store import get_calendar_store
    store = get_calendar_store()
    if store.delete_event(uid):
        return f"Event {uid[:8]} deleted."
    return f"No event found with id '{uid}'."


def _ha_config():
    from core.config import get_config
    cfg = get_config()
    if not cfg.hass_url or not cfg.hass_token:
        return None, None, "Home Assistant not configured. Set hass_url and hass_token in Settings → Home."
    return cfg.hass_url.rstrip("/"), cfg.hass_token, None


@tool(description="Toggle a Home Assistant entity on or off. entity_id example: 'light.living_room'.")
def toggle_entity(entity_id: str) -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(
            f"{url}/api/services/homeassistant/toggle",
            headers=headers,
            json={"entity_id": entity_id},
            timeout=10.0,
        )
        if resp.status_code == 404:
            return f"Entity not found: {entity_id!r}"
        resp.raise_for_status()
        return f"Toggled {entity_id}."
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"


@tool(description="Get the current state of a Home Assistant entity. entity_id example: 'light.living_room'.")
def get_entity_state(entity_id: str) -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.get(f"{url}/api/states/{entity_id}", headers=headers, timeout=10.0)
        if resp.status_code == 404:
            return f"Entity not found: {entity_id!r}"
        resp.raise_for_status()
        data = resp.json()
        return f"{entity_id}: {data.get('state', 'unknown')}"
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"


@tool(description="List Home Assistant entities, optionally filtered by domain (e.g. 'light', 'switch', 'sensor').")
def list_home_entities(domain: str = "") -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.get(f"{url}/api/states", headers=headers, timeout=10.0)
        resp.raise_for_status()
        states = resp.json()
        if domain:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        if not states:
            return f"No entities found{' for domain ' + domain if domain else ''}."
        lines = [f"- {s['entity_id']}: {s.get('state', '?')}" for s in states[:30]]
        suffix = f"\n(showing 30 of {len(resp.json())})" if domain == "" and len(states) > 30 else ""
        return "\n".join(lines) + suffix
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"


@tool(description="Execute Python code in a sandbox and return output. Useful for calculations, data processing, or quick scripts.")
def run_python_code(code: str) -> str:
    from agents.code_sandbox import run_python
    return run_python(code)


@tool(description="Run a shell command in a restricted sandbox and return output. Useful for file listings, text processing, system info.")
def run_shell_command(command: str) -> str:
    from agents.code_sandbox import run_shell
    return run_shell(command)


@tool(description="Fetch and read the text content of a web page. Use for reading articles, docs, or any URL.")
def scrape_url(url: str) -> str:
    import re
    import httpx
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:2000] or "(no content)"
    except httpx.HTTPError as exc:
        return f"Fetch error: {exc}"


@tool(description="Search the web for current information. Returns top results with title, snippet, and URL.")
def search_web(query: str) -> str:
    from core.config import get_config
    from agents.web_search import search_ddg, search_google
    cfg = get_config()
    provider = cfg.web_search_default
    max_results = cfg.web_search_max_results
    if provider == "google" and cfg.google_search_api_key and cfg.google_search_cx:
        results = search_google(query, cfg.google_search_api_key, cfg.google_search_cx, max_results)
    else:
        results = search_ddg(query, max_results)
    if not results:
        return "No results found."
    return "\n\n".join(results)


@tool(description="Mute system audio output.")
def mute_audio() -> str:
    import subprocess
    try:
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
                       check=True, capture_output=True, timeout=5)
        return "Audio muted."
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Unmute system audio output.")
def unmute_audio() -> str:
    import subprocess
    try:
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                       check=True, capture_output=True, timeout=5)
        return "Audio unmuted."
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Set system audio volume. percent must be 0–100.")
def set_volume(percent: int) -> str:
    import subprocess
    if not 0 <= percent <= 100:
        return "Volume must be 0–100."
    level = percent / 100
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"],
            check=True, capture_output=True, timeout=5,
        )
        return f"Volume set to {percent}%."
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Get current system audio volume as a percentage.")
def get_volume() -> str:
    import subprocess
    import re
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        match = re.search(r"[\d.]+", result.stdout)
        if not match:
            return "Could not parse volume."
        percent = round(float(match.group()) * 100)
        muted = "[MUTED]" in result.stdout
        return f"Volume: {percent}%{' (muted)' if muted else ''}"
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Get current system resource usage: CPU percent, RAM used/total, and disk used/total.")
def get_system_info() -> str:
    import psutil
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    ram_used = ram.used / 1024 ** 3
    ram_total = ram.total / 1024 ** 3
    disk_used = disk.used / 1024 ** 3
    disk_total = disk.total / 1024 ** 3
    return (
        f"CPU: {cpu:.1f}%  "
        f"RAM: {ram_used:.1f}/{ram_total:.1f} GB ({ram.percent:.1f}%)  "
        f"Disk: {disk_used:.1f}/{disk_total:.1f} GB ({disk.percent:.1f}%)"
    )


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
