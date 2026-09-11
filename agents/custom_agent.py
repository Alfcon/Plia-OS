from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

import agents.llm
import core.registry
from core.agent_store import get_agent

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_TOOL_CALL_LIMIT = 10


async def custom_agent_node(state: "AgentState") -> dict:
    name = state["active_agent"].removeprefix("custom:")
    defn = await asyncio.to_thread(get_agent, name)
    if not defn or not defn.enabled:
        return {"tool_results": [f"Custom agent '{name}' not found or disabled"]}

    if defn.workflow_name:
        from agents.workflow_store import run_workflow
        user_msg = next(
            (m["content"] for m in state["messages"] if m["role"] == "user"), ""
        )
        try:
            output = await run_workflow(defn.workflow_name, payload={"message": user_msg})
        except KeyError:
            return {"tool_results": [f"Workflow '{defn.workflow_name}' not found"]}
        if output and output[-1].get("error"):
            return {"tool_results": [f"Workflow error: {output[-1]['error']}"]}
        return {"tool_results": [output[-1]["result"] if output else ""]}

    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    all_tools = core.registry.get_tool_schemas()
    tools = [t for t in all_tools if t["function"]["name"] in defn.tool_names]

    content = ""
    for _ in range(_TOOL_CALL_LIMIT):
        msg = await agents.llm.call_llm(messages, tools=tools or None)
        messages.append(msg)
        if not msg.get("tool_calls"):
            content = msg.get("content") or ""
            break
        for tc in msg["tool_calls"]:
            fn = tc["function"]
            try:
                result = await core.registry.call_tool_async(fn["name"], fn.get("arguments") or {})
            except Exception as exc:
                result = f"[Tool error: {exc}]"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result),
            })
    else:
        content = "[Tool call limit reached]"
    return {"tool_results": [content]}
