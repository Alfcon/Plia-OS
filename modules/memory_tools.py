from core.registry import tool


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


@tool(description="Forget a stored memory fact. Leave key blank to list all memories numbered. Pass a number (e.g. '3') to forget that entry. Pass an exact key to forget directly.")
def forget_memory(key: str = "") -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    facts = store.list_all()

    if not key.strip():
        if not facts:
            return "No memories stored."
        lines = [f"{i + 1}. {f['key']}: {f['value']}" for i, f in enumerate(facts)]
        return "Memories (enter a number to forget one):\n" + "\n".join(lines)

    if key.strip().isdigit():
        idx = int(key.strip()) - 1
        if 0 <= idx < len(facts):
            target = facts[idx]["key"]
            store.forget(target)
            return f"Forgotten #{idx + 1}: '{target}'."
        return f"No memory at position {key}. Leave key blank to see the list."

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


@tool(description="Add a quick note. Unlike save_memory, no key needed — just the text to remember.")
def add_note(text: str) -> str:
    from datetime import datetime, timezone
    from agents.memory_store import get_memory_store
    key = f"note_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    get_memory_store().remember(key, text)
    return f"Note saved: {text}"


@tool(description="List all saved notes.")
def list_notes() -> str:
    from agents.memory_store import get_memory_store
    facts = get_memory_store().list_all()
    notes = [f for f in facts if f["key"].startswith("note_")]
    if not notes:
        return "No notes saved."
    return "\n".join(f"- {n['value']}" for n in notes)


@tool(description="Delete a specific note by matching text. Deletes the first note containing the given text.")
def delete_note(text: str) -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    notes = [f for f in store.list_all() if f["key"].startswith("note_")]
    match = next((n for n in notes if text.lower() in n["value"].lower()), None)
    if not match:
        return f"No note found matching '{text}'."
    store.forget(match["key"])
    return f"Deleted note: {match['value']}"


@tool(description="Delete all saved notes.")
def clear_notes() -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    notes = [f for f in store.list_all() if f["key"].startswith("note_")]
    if not notes:
        return "No notes to clear."
    for n in notes:
        store.forget(n["key"])
    return f"Cleared {len(notes)} note{'s' if len(notes) != 1 else ''}."
