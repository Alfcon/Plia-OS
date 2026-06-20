"""
Tool approval gate. When a tool name is in config.tool_guard_list, execution
is paused until the user approves or denies via the dashboard.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_pending: dict[str, "_PendingApproval"] = {}


class ToolDeniedError(Exception):
    """Raised when the user denies a guarded tool call."""


class _PendingApproval:
    def __init__(self, tool_name: str, arguments: dict) -> None:
        self.id = str(uuid.uuid4())
        self.tool_name = tool_name
        self.arguments = arguments
        self._event = asyncio.Event()
        self.approved: bool = False

    def resolve(self, approved: bool) -> None:
        self.approved = approved
        self._event.set()

    async def wait(self, timeout: float = 120.0) -> bool:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Tool guard timeout for %s (id=%s)", self.tool_name, self.id)
            return False
        return self.approved


def _is_guarded(tool_name: str) -> bool:
    from core.config import get_config
    return tool_name in (get_config().tool_guard_list or [])


async def maybe_guard(tool_name: str, arguments: dict[str, Any]) -> None:
    """
    If tool_name is guarded, broadcast a WebSocket approval request and wait.
    Raises ToolDeniedError if denied or timed out.
    """
    if not _is_guarded(tool_name):
        return

    approval = _PendingApproval(tool_name, arguments)
    _pending[approval.id] = approval
    logger.info("Tool guard: waiting for approval of %s (id=%s)", tool_name, approval.id)

    try:
        from core import events
        await events.emit("tool_approval_request", {
            "id": approval.id,
            "tool": tool_name,
            "arguments": arguments,
        })
        ok = await approval.wait()
    finally:
        _pending.pop(approval.id, None)

    if not ok:
        raise ToolDeniedError(f"Tool '{tool_name}' was denied by user.")


def respond(approval_id: str, approved: bool) -> bool:
    """Called by the API endpoint. Returns False if approval_id unknown."""
    ap = _pending.get(approval_id)
    if ap is None:
        return False
    ap.resolve(approved)
    return True
