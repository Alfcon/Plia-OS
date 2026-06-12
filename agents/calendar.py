from __future__ import annotations
import datetime
import json
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.calendar_store import get_calendar_store

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the calendar request. Output JSON with these keys: "
    '"op" ("add", "list", or "delete"), '
    '"title" (event name, for add), '
    '"date" (YYYY-MM-DD, for add), '
    '"time" (HH:MM, for add, default "09:00"), '
    '"duration" (integer minutes, for add, default 60), '
    '"uid" (full uid string, for delete). '
    "Omit keys not relevant to the operation. "
    "Output only valid JSON, no explanation."
)


async def calendar_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = json.loads(msg.get("content") or "{}")
        op = parsed.get("op", "list")
    except Exception as exc:
        logger.warning("Calendar LLM parse failed, falling back to list: %s", exc)
        op, parsed = "list", {}

    store = get_calendar_store()

    if op == "add":
        title = parsed.get("title", "Untitled")
        date_str = parsed.get("date", datetime.date.today().isoformat())
        time_str = parsed.get("time", "09:00")
        duration = int(parsed.get("duration", 60))
        uid = store.add_event(title, date_str, time_str, duration)
        result = f"Added event '{title}' on {date_str} at {time_str} (uid: {uid[:8]})"
    elif op == "delete":
        uid = parsed.get("uid", "")
        deleted = store.delete_event(uid)
        result = (
            f"Deleted event {uid[:8]}" if deleted else f"Event {uid[:8] if uid else '?'} not found"
        )
    else:
        events = store.list_events()
        result = "\n".join(events)

    logger.info("Calendar op=%s", op)
    return {
        "tool_results": state["tool_results"] + [f"[calendar]\n{result}"],
        "active_agent": "calendar",
    }
