from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def calendar_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[calendar] not yet implemented"],
        "active_agent": "calendar",
    }
