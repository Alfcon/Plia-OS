from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from modules.network_tools import list_macs, show_mac, randomize_mac, set_mac, restore_mac

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the network MAC address request. Current UTC time: {now}. "
    'Output JSON with exactly three keys: '
    '"action" (one of: show, randomize, change, set, restore), '
    '"interface" (interface name string or null for auto-detect), '
    '"mac" (MAC address string for set action, otherwise null). '
    'Use "change" or "randomize" when the user wants to mask or change their MAC to a random address. '
    'Use "set" only when the user provides a specific MAC address. '
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[network]\nCouldn't parse that request. "
    "Try: 'show my MAC', 'change MAC on wlan0', "
    "'set MAC to AA:BB:CC:DD:EE:FF', 'restore original MAC'."
)

_ACTIONS = {"show", "randomize", "change", "set", "restore"}


async def network_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )
    now = datetime.now(timezone.utc).isoformat()

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM.format(now=now)},
            {"role": "user", "content": last_user},
        ])
        parsed = parse_llm_json(msg.get("content"))
        action = str(parsed.get("action") or "").strip().lower()
        interface = str(parsed.get("interface") or "").strip()
        mac = str(parsed.get("mac") or "").strip()
        if action not in _ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
    except Exception:
        logger.exception("Network parse failed for: %r", last_user)
        return {
            "tool_results": state["tool_results"] + [_FALLBACK_MSG],
            "active_agent": "network",
        }

    try:
        if action == "show":
            result = await asyncio.to_thread(list_macs) if not interface else await asyncio.to_thread(show_mac, interface)
        elif action in ("randomize", "change"):
            result = await asyncio.to_thread(randomize_mac, interface)
        elif action == "set":
            result = await asyncio.to_thread(set_mac, interface, mac)
        else:  # restore
            result = await asyncio.to_thread(restore_mac, interface)
    except Exception:
        logger.exception("Network tool failed for action=%r", action)
        result = "Network operation failed. Please try again."

    return {
        "tool_results": state["tool_results"] + [f"[network]\n{result}"],
        "active_agent": "network",
    }
