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


async def custom_agent_node(state: "AgentState") -> dict:
    name = state["active_agent"].removeprefix("custom:")
    defn = await asyncio.to_thread(get_agent, name)
    if not defn or not defn.enabled:
        return {"tool_results": [f"Custom agent '{name}' not found or disabled"]}

    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    all_tools = core.registry.get_tool_schemas()
    tools = [t for t in all_tools if t["function"]["name"] in defn.tool_names]
    msg = await agents.llm.call_llm(messages, tools=tools or None)
    content = msg.get("content") or ""
    if not content and msg.get("tool_calls"):
        content = "[Custom agent attempted a tool call but tool execution is not yet supported in Phase 1.]"
    return {"tool_results": [content]}
