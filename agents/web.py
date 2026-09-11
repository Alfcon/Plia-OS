from __future__ import annotations
import logging
import re
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.web_search import web_search
from core.config import get_config

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")

_EXTRACT_SYSTEM = (
    "Extract the search query or URL from the user's message. "
    "Output only the query string or URL, nothing else."
)

_STRIP_PREFIXES = (
    "search for ", "search the web for ", "look up ", "look it up ",
    "google ", "find online ", "look online for ", "browse to ", "visit ",
    "search ", "find ",
)

_GOOGLE_KEYWORDS = ("google", "search with google", "use google", "google search")
_PLAYWRIGHT_KEYWORDS = ("open ", "read this page", "visit ", "browse to", "go to http")


def _detect_provider(text: str, default: str) -> str:
    lower = text.lower()
    if _URL_RE.search(text):
        return "playwright"
    if any(kw in lower for kw in _GOOGLE_KEYWORDS):
        return "google"
    if any(kw in lower for kw in _PLAYWRIGHT_KEYWORDS):
        return "playwright"
    return default


async def web_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )
    config = get_config()
    provider = _detect_provider(last_user, state.get("search_provider", "ddg"))

    lower = last_user.lower()
    query = last_user
    for prefix in _STRIP_PREFIXES:
        if lower.startswith(prefix):
            query = last_user[len(prefix):].strip()
            break
    else:
        try:
            msg = await call_llm([
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": last_user},
            ])
            query = (msg.get("content") or last_user).strip() or last_user
        except Exception:
            query = last_user

    results = await web_search(query, provider, config)
    combined = "\n".join(results)
    logger.info("Web search (%s): %d results", provider, len(results))
    return {
        "tool_results": state["tool_results"] + [f"[web/{provider}]\n{combined}"],
        "active_agent": "web",
    }
