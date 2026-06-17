from __future__ import annotations
import asyncio
import logging
import re
from typing import TYPE_CHECKING

from modules.network_tools import list_macs, show_mac, randomize_mac, set_mac, restore_mac

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_MAC_IN_TEXT = re.compile(r"\b([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b")
_IFACE_HINT = re.compile(r"\b(?:on|for|of|interface)\s+([A-Za-z0-9_@.-]+)", re.IGNORECASE)
_IFACE_NAME = re.compile(r"\b(eth\d+|wlan\d+|ens\d+|enp\w+|wlp\w+|tun\d+|tap\d+|br\w+|bond\d+)\b", re.IGNORECASE)

_RESTORE_KW = re.compile(r"\b(?:restore|revert|reset|original|undo)\b", re.IGNORECASE)
_RANDOMIZE_KW = re.compile(r"\b(?:random(?:ize)?|change|mask|spoof|fake|anonymi[sz]e)\b", re.IGNORECASE)
_SHOW_KW = re.compile(r"\b(?:show|list|display|what|current|check|get|view|my)\b", re.IGNORECASE)

_FALLBACK_MSG = (
    "[network]\nCouldn't parse that request. "
    "Try: 'show my MAC', 'change MAC on wlan0', "
    "'set MAC to AA:BB:CC:DD:EE:FF', 'restore original MAC'."
)


def _parse_request(text: str) -> tuple[str, str, str]:
    """Return (action, interface, mac). interface/mac may be empty string."""
    mac_match = _MAC_IN_TEXT.search(text)
    mac = mac_match.group(1) if mac_match else ""

    hint = _IFACE_HINT.search(text)
    if hint:
        interface = hint.group(1).rstrip(".,;:")
    else:
        name_match = _IFACE_NAME.search(text)
        interface = name_match.group(1) if name_match else ""

    if mac:
        action = "set"
    elif _RESTORE_KW.search(text):
        action = "restore"
    elif _RANDOMIZE_KW.search(text):
        action = "randomize"
    else:
        action = "show"

    return action, interface, mac


async def network_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    action, interface, mac = _parse_request(last_user)
    logger.debug("network_node: action=%r interface=%r mac=%r", action, interface, mac)

    try:
        if action == "show":
            if interface:
                result = await asyncio.to_thread(show_mac, interface)
            else:
                result = await asyncio.to_thread(list_macs)
        elif action == "randomize":
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
