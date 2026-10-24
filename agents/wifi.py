from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the WiFi request. "
    'Output JSON with exactly four keys: '
    '"action" (one of: status, scan, interfaces, connect, saved, password, gain, reveal), '
    '"interface" (interface name string or null for auto-detect), '
    '"ssid" (network name string or null), '
    '"password" (string or null). '
    "Use 'status' for current connection info. "
    "Use 'scan' to list nearby networks. "
    "Use 'interfaces' to list WiFi interfaces on this system. "
    "Use 'connect' to join a WiFi network (leave ssid null to auto-connect "
    "to the strongest saved network; password is usually null because saved "
    "credentials are reused). "
    "Use 'saved' to list saved WiFi networks. "
    "Use 'password' when the user asks for the saved WiFi password of the network "
    "this machine is connected to (for example 'what is my wifi password', "
    "'show the saved wifi password', 'find the password for the wifi'). "
    "Use 'gain' only when the user wants to get access to a network they do not "
    "have the password for — never use 'gain' for the current/saved password. "
    "Use 'reveal' to reveal the names of hidden WiFi networks. "
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[wifi]\nCouldn't parse that request. "
    "Try: 'wifi status', 'scan for wifi networks', 'list wifi interfaces', "
    "'connect to my wifi', 'connect to the Home network', 'list saved wifi', "
    "'what is my wifi password'."
)

_ACTIONS = {"status", "scan", "interfaces", "connect", "saved", "password", "gain", "reveal"}


_PASSWORD_HINTS = (
    "wifi password", "wi-fi password", "wifi pass", "wi-fi pass",
    "saved password", "saved wifi password", "current wifi password",
    "show the password", "show password", "what is the password",
    "what's the password", "find the password", "get the password",
    "forgot my wifi password", "forgot the wifi password",
)
_ACCESS_HINTS = (
    "don't have", "do not have", "no password", "without the password",
    "crack", "hack", "get access", "gain access", "forgot the password",
)


def _is_saved_password_request(text: str) -> bool:
    """True for "show my saved WiFi password", false for "get access without it"."""
    low = (text or "").lower()
    if any(h in low for h in _ACCESS_HINTS):
        return False
    return any(h in low for h in _PASSWORD_HINTS)


async def wifi_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    action = interface = ssid = password = ""
    if _is_saved_password_request(last_user):
        # Works even when the LLM is offline; this is a local lookup, not an attack.
        action = "password"
    else:
        try:
            msg = await call_llm([
                {"role": "system", "content": _PARSE_SYSTEM},
                {"role": "user", "content": last_user},
            ])
            parsed = parse_llm_json(msg.get("content"))
            action = str(parsed.get("action") or "").strip().lower()
            interface = str(parsed.get("interface") or "").strip()
            ssid = str(parsed.get("ssid") or "").strip()
            password = str(parsed.get("password") or "").strip()
            if action not in _ACTIONS:
                raise ValueError(f"unknown action: {action!r}")
        except Exception:
            logger.exception("WiFi parse failed for: %r", last_user)
            return {
                "tool_results": state["tool_results"] + [_FALLBACK_MSG],
                "active_agent": "wifi",
            }

    # Resolve tools per call: modules/* can be hot-reloaded without restarting
    # the dashboard, and the agent must not keep stale bound functions.
    from modules.network_tools import (
        wifi_status, scan_wifi, list_wifi_interfaces, connect_wifi,
        list_saved_wifi,
    )
    from modules.wireless_tools import gain_wifi_access, reveal_hidden_ssid
    from modules.network_check_tools import check_wifi_password

    try:
        if action == "status":
            result = await asyncio.to_thread(wifi_status)
        elif action == "scan":
            result = await asyncio.to_thread(scan_wifi, interface)
        elif action == "connect":
            result = await asyncio.to_thread(connect_wifi, ssid, interface, password)
        elif action == "saved":
            result = await asyncio.to_thread(list_saved_wifi)
        elif action == "password":
            result = await asyncio.to_thread(check_wifi_password)
        elif action == "gain":
            result = await asyncio.to_thread(gain_wifi_access, ssid, interface)
        elif action == "reveal":
            result = await asyncio.to_thread(reveal_hidden_ssid, interface)
        else:  # interfaces
            result = await asyncio.to_thread(list_wifi_interfaces)
    except Exception:
        logger.exception("WiFi tool failed for action=%r", action)
        result = "WiFi operation failed. Please try again."

    return {
        "tool_results": state["tool_results"] + [f"[wifi]\n{result}"],
        "active_agent": "wifi",
    }
