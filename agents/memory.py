from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from agents.memory_store import get_memory_store

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the user memory request. Output JSON with exactly three keys: "
    '"op" ("remember", "recall", or "forget"), '
    '"key" (short identifier string), '
    '"value" (the fact to store, or empty string). '
    "Output only valid JSON, no explanation."
)


async def memory_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        parse_messages = [
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ]
        msg = await call_llm(parse_messages)
        parsed = parse_llm_json(msg.get("content"))
        op = parsed.get("op", "recall")
        key = parsed.get("key", last_user[:80])
        value = parsed.get("value", "")
    except Exception:
        op, key, value = "recall", last_user[:80], ""

    store = get_memory_store()

    if op == "remember" and key and value:
        store.remember(key, value)
        result = f"Remembered: {key} = {value}"
        return {
            "tool_results": state["tool_results"] + [result],
            "active_agent": "memory",
        }

    if op == "forget" and key:
        store.forget(key)
        result = f"Forgot: {key}"
        return {
            "tool_results": state["tool_results"] + [result],
            "active_agent": "memory",
        }

    snippets = store.recall(last_user)
    context = "\n".join(snippets)
    logger.info("Memory recall: %d snippets", len(snippets))
    return {
        "tool_results": state["tool_results"] + [f"[memory]\n{context}"],
        "active_agent": "memory",
        "memory_context": context,
    }
