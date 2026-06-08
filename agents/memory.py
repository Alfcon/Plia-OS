from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def memory_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[memory] not yet implemented"],
        "active_agent": "memory",
    }
