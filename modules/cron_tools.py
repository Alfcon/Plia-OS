from __future__ import annotations
from core.registry import tool


def _validate_expr(expr: str) -> str | None:
    """Return None if valid, error string if not."""
    try:
        from croniter import croniter
        if not croniter.is_valid(expr):
            return f"Invalid cron expression: {expr!r}"
        return None
    except ImportError:
        return "croniter not installed. Run: pip install croniter"


@tool(
    "Add or replace a recurring cron job. "
    "expr is a standard 5-field cron expression (minute hour dom month dow). "
    "Examples: '0 8 * * 1-5' = weekdays 8am, '*/30 * * * *' = every 30 min. "
    "message is what Plia will announce when the cron fires."
)
def add_cron(name: str, expr: str, message: str) -> str:
    err = _validate_expr(expr)
    if err:
        return err
    from agents.cron_store import get_cron_store
    get_cron_store().add(name, expr, message)
    return f"Cron job '{name}' scheduled: {expr} — will announce: {message!r}"


@tool("List all scheduled cron jobs (name, expression, message, enabled status).")
def list_crons() -> str:
    from agents.cron_store import get_cron_store
    jobs = get_cron_store().list_all()
    if not jobs:
        return "No cron jobs scheduled."
    lines = []
    for j in jobs:
        status = "✓" if j["enabled"] else "✗"
        lines.append(f"{status} [{j['name']}] {j['expr']} — {j['message']}")
    return "\n".join(lines)


@tool("Remove a scheduled cron job by name.")
def remove_cron(name: str) -> str:
    from agents.cron_store import get_cron_store
    removed = get_cron_store().remove(name)
    return f"Cron job '{name}' removed." if removed else f"No cron job named '{name}'."


@tool("Pause a cron job without deleting it.")
def disable_cron(name: str) -> str:
    from agents.cron_store import get_cron_store
    ok = get_cron_store().set_enabled(name, False)
    return f"Cron job '{name}' paused." if ok else f"No cron job named '{name}'."


@tool("Resume a previously paused cron job.")
def enable_cron(name: str) -> str:
    from agents.cron_store import get_cron_store
    ok = get_cron_store().set_enabled(name, True)
    return f"Cron job '{name}' enabled." if ok else f"No cron job named '{name}'."
