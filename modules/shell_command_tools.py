from __future__ import annotations

import asyncio
import logging
from typing import Literal

from core.registry import tool

logger = logging.getLogger(__name__)

_LAST_PROPOSAL: dict | None = None


@tool(
    "Propose a REAL shell command for a system task the sandbox can't do (real files, disk, "
    "processes). You translate the user's request into the exact command and a plain-English "
    "explanation. This does NOT run it — it shows the command for the user to confirm; "
    "run_proposed_command executes it after approval. "
    "command: the exact shell command. explanation: what it does and any risk."
)
def propose_command(command: str, explanation: str, risk: Literal["", "low", "medium", "high"] = "") -> str:
    global _LAST_PROPOSAL
    from agents.shell_exec import blocked_reason
    reason = blocked_reason(command)
    if reason:
        return f"{reason} I won't propose that command."
    _LAST_PROPOSAL = {"command": command, "explanation": explanation, "risk": risk}
    lines = [
        "Proposed command (needs your approval to run):",
        f"  $ {command}",
        f"What it does: {explanation}",
    ]
    if risk:
        lines.append(f"Risk: {risk}")
    lines.append("Say yes to run it (via run_proposed_command).")
    return "\n".join(lines)


@tool(
    "Run a command previously staged by propose_command, in the REAL environment. Always "
    "requires user approval (the approval dialog shows the command). Pass the exact command "
    "from the proposal. Call this only after the user agrees."
)
async def run_proposed_command(command: str) -> str:
    global _LAST_PROPOSAL
    from agents.shell_exec import blocked_reason, exec_real
    if _LAST_PROPOSAL is None:
        return "No command proposed. Use propose_command first."
    if command != _LAST_PROPOSAL["command"]:
        return "That does not match the proposed command. Re-run propose_command."
    reason = blocked_reason(command)
    if reason:
        _LAST_PROPOSAL = None
        return f"{reason} Not running."
    logger.info("Running approved real command: %s", command)
    result = await asyncio.to_thread(exec_real, command)
    _LAST_PROPOSAL = None
    return result
