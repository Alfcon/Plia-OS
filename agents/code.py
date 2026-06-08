from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def code_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[code] not yet implemented"],
        "active_agent": "code",
    }
