from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from modules.weather_tools import get_current_weather, get_forecast, get_uv_index

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the weather request. "
    'Output JSON with exactly two keys: '
    '"action" (one of: current, forecast, uv), '
    '"location" (city name string, or empty string to use the configured default). '
    "Use 'current' for current conditions or temperature. "
    "Use 'forecast' for multi-day outlook, rain predictions, or future weather. "
    "Use 'uv' for UV index or sun protection queries. "
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[weather]\nCouldn't parse that weather request. "
    "Try: 'weather in Berlin', 'forecast for Tokyo', 'UV index'."
)

_ACTIONS = {"current", "forecast", "uv"}


async def weather_node(state: "AgentState") -> dict:
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
        location = str(parsed.get("location") or "").strip()
        if action not in _ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
    except Exception:
        logger.exception("Weather parse failed for: %r", last_user)
        return {
            "tool_results": state["tool_results"] + [_FALLBACK_MSG],
            "active_agent": "weather",
        }

    try:
        if action == "current":
            result = await asyncio.to_thread(get_current_weather, location)
        elif action == "forecast":
            result = await asyncio.to_thread(get_forecast, location)
        else:  # uv
            result = await asyncio.to_thread(get_uv_index, location)
    except Exception:
        logger.exception("Weather tool failed for action=%r", action)
        result = "Weather lookup failed. Please try again."

    return {
        "tool_results": state["tool_results"] + [f"[weather]\n{result}"],
        "active_agent": "weather",
    }
