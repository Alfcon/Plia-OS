from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.code_sandbox import run_python, run_shell

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "Extract the code from the user's message. "
    'Output JSON with two keys: "language" ("python" or "shell") and "code" (the code string). '
    "Output only valid JSON, no explanation."
)


async def code_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = json.loads(msg.get("content", "{}"))
        language = parsed.get("language", "python")
        code = parsed.get("code", "")
    except Exception:
        language, code = "python", ""

    if not code:
        output = "Could not extract code from the request."
    elif language == "shell":
        output = run_shell(code)
    else:
        output = run_python(code)

    logger.info("Code execution (%s): %d chars output", language, len(output))
    return {
        "tool_results": state["tool_results"] + [f"[code/{language}]\n{output}"],
        "active_agent": "code",
    }
