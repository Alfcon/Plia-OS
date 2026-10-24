from core.registry import tool


@tool(description="Get the current time in HH:MM format")
def get_time() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


@tool(description="Get the current date including day of week, month, day, and year")
def get_current_date() -> str:
    from datetime import datetime
    return datetime.now().strftime("%A, %B %d, %Y")


@tool(description="List all available tools with their descriptions. Use when asked 'what can you do?' or 'what tools do you have?'")
def list_tools() -> str:
    from core.registry import get_tool_schemas
    schemas = get_tool_schemas()
    if not schemas:
        return "No tools registered."
    lines = [f"- {s['function']['name']}: {s['function'].get('description', '')}" for s in schemas]
    return f"{len(lines)} tools available:\n" + "\n".join(lines)
