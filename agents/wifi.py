from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from modules.network_tools import (
    wifi_status, scan_wifi, list_wifi_interfaces, connect_wifi, list_saved_wifi,
)

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the WiFi request. "
    'Output JSON with exactly four keys: '
    '"action" (one of: status, scan, interfaces, connect, saved), '
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
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[wifi]\nCouldn't parse that request. "
    "Try: 'wifi status', 'scan for wifi networks', 'list wifi interfaces', "
    "'connect to my wifi', 'connect to the Home network', 'list saved wifi'."
)

_ACTIONS = {"status", "scan", "interfaces", "connect", "saved"}


async def wifi_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

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

    try:
        if action == "status":
            result = await asyncio.to_thread(wifi_status)
        elif action == "scan":
            result = await asyncio.to_thread(scan_wifi, interface)
        elif action == "connect":
            result = await asyncio.to_thread(connect_wifi, ssid, interface, password)
        elif action == "saved":
            result = await asyncio.to_thread(list_saved_wifi)
        else:  # interfaces
            result = await asyncio.to_thread(list_wifi_interfaces)
    except Exception:
        logger.exception("WiFi tool failed for action=%r", action)
        result = "WiFi operation failed. Please try again."

    return {
        "tool_results": state["tool_results"] + [f"[wifi]\n{result}"],
        "active_agent": "wifi",
    }
