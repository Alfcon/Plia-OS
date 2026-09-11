from __future__ import annotations

from core.registry import tool


@tool(
    "Control the desktop to accomplish a goal: repeatedly look at the screen and "
    "click/type until done. Requires approval to start. X11 + xdotool only. "
    "goal: what to accomplish. max_steps: safety cap on actions (default 15)."
)
async def use_computer(goal: str, max_steps: int = 15) -> str:
    from agents.computer_use import run_computer_use
    return await run_computer_use(goal, max_steps)
