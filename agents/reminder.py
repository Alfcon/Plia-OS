from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from agents.memory_store import get_memory_store

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the reminder request. Current UTC time: {now}. "
    'Output JSON with exactly two keys: "message" (what to remind about, concise) '
    'and "fire_at" (ISO 8601 datetime with UTC timezone offset, '
    'e.g. "2026-06-13T15:00:00+00:00"). '
    "If no time is specified, default to 5 minutes from now. "
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[reminder]\nCouldn't parse that reminder. "
    "Try: 'remind me to call John at 3pm tomorrow'."
)


async def reminder_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )
    now = datetime.now(timezone.utc).isoformat()

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM.format(now=now)},
            {"role": "user", "content": last_user},
        ])
        parsed = parse_llm_json(msg.get("content"))
        message = str(parsed.get("message") or "").strip()
        fire_at = str(parsed.get("fire_at") or "").strip()
        if not message or not fire_at:
            raise ValueError("missing fields")
    except Exception:
        logger.exception("Reminder parse failed for: %r", last_user)
        return {
            "tool_results": state["tool_results"] + [_FALLBACK_MSG],
            "active_agent": "reminder",
        }

    store = get_memory_store()
    reminder_id = store.add_reminder(message, fire_at)
    logger.info("Reminder created: id=%d message=%r fire_at=%s", reminder_id, message, fire_at)
    result = f"Reminder set: '{message}' at {fire_at}"
    return {
        "tool_results": state["tool_results"] + [f"[reminder]\n{result}"],
        "active_agent": "reminder",
    }
