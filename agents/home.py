from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.home_assistant import call_service, get_state, list_states
from core.config import get_config

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_KNOWN_OPS = {"call_service", "get_state", "list_states"}


def _parse_llm_json(content: str | None) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text or "{}")


_PARSE_SYSTEM = (
    "Parse the home automation request. Output JSON with these keys: "
    '"op": one of "call_service", "get_state", "list_states". '
    'For "call_service": "domain" (e.g. "light", "switch", "climate"), '
    '"service" (e.g. "turn_on", "turn_off", "toggle"), '
    '"entity_id" (e.g. "light.kitchen", or "all" for all entities in domain). '
    'For "get_state": "entity_id". '
    'For "list_states": optionally "domain" to filter (e.g. "light"). '
    "Output only valid JSON, no explanation."
)


async def home_node(state: "AgentState") -> dict:
    config = get_config()

    if not config.hass_url or not config.hass_token:
        return {
            "tool_results": state["tool_results"] + [
                "[home] Home Assistant not configured. Set hass_url and hass_token in Settings → Home."
            ],
            "active_agent": "home",
        }

    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = _parse_llm_json(msg.get("content"))
        op = parsed.get("op", "")
        if op not in _KNOWN_OPS:
            op = "list_states"
    except Exception as exc:
        logger.warning("Home LLM parse failed: %s", exc)
        return {
            "tool_results": state["tool_results"] + [f"[home] Failed to parse request: {exc}"],
            "active_agent": "home",
        }

    try:
        if op == "call_service":
            result = await call_service(
                config.hass_url,
                config.hass_token,
                parsed.get("domain", "homeassistant"),
                parsed.get("service", "toggle"),
                parsed.get("entity_id"),
            )
        elif op == "get_state":
            entity_id = parsed.get("entity_id", "").strip()
            if not entity_id:
                result = "Please specify which entity to query (e.g. 'sensor.temp')."
            else:
                result = await get_state(config.hass_url, config.hass_token, entity_id)
        else:
            result = await list_states(config.hass_url, config.hass_token, parsed.get("domain"))
    except Exception as exc:
        logger.warning("Home Assistant request failed: %s", exc)
        result = f"Home Assistant error: {exc}"

    logger.info("Home op=%s result=%s", op, result[:80])
    return {
        "tool_results": state["tool_results"] + [f"[home]\n{result}"],
        "active_agent": "home",
    }
