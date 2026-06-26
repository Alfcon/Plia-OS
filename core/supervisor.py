from __future__ import annotations
import asyncio
import logging
import re
from typing import TypedDict
from langgraph.graph import StateGraph, END
from core.config import get_config
from core.registry import get_tool_schemas, call_tool_async, ToolExecutionError
from agents.llm import call_llm
from agents.memory import memory_node
from agents.memory_store import get_memory_store
from agents.web import web_node
from core import events
from agents.code import code_node
from agents.calendar import calendar_node
from agents.home import home_node
from agents.reminder import reminder_node
from agents.network import network_node
from agents.wifi import wifi_node
from agents.file import file_node
from agents.weather import weather_node
logger = logging.getLogger(__name__)

_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file", "weather", "cron"}
_HOP_LIMIT = 5
_TOOL_CALL_LIMIT = 10

_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder, network, wifi, file, weather, cron. "
    "Use 'reminder' for one-shot announcements at a specific future time ('remind me at 3pm', 'notify me in 2 hours'). "
    "Use 'cron' for recurring schedules ('every day at 8am', 'every weekday', 'every 30 minutes', cron job management). "
    "Use 'home' only for Home Assistant device control (lights, switches, sensors). "
    "Use 'network' for MAC address operations (show, change, randomize, spoof, restore MAC address). "
    "Use 'wifi' for WiFi status, scanning nearby networks, or listing WiFi interfaces. "
    "Use 'file' for reading, writing, finding, searching, or running files and directories; also PDF, Word, Excel, PowerPoint documents. "
    "Use 'weather' for weather conditions, forecasts, temperature, rain, UV index, or climate queries. "
    "Use 'respond' for countdown timers, volume, system info, calculations, or anything answerable with tools directly."
)

_KEYWORD_ROUTES: dict[str, list[str]] = {
    "memory": ["remember that", "remember this", "recall what",
               "what did i tell you", "store this", "store that", "save that", "memorize",
               "i want you to remember"],
    "file": [
        "read the file", "show me the file", "open the file", "what's in",
        "contents of", "list files", "list directory", "what files",
        "show files in", "find files", "find the file", "search in file",
        "search in", "grep ", "create a file", "write to file", "make a file",
        "save to file", "delete the file", "remove the file",
        "move the file", "rename the file", "copy the file",
        "run the file", "run the script", "execute the file",
        "read the pdf", "open the pdf", "summarize the pdf", "read pdf",
        "read the document", "open the document", "summarize the document",
        "read the docx", "read the word", "read the spreadsheet",
        "read the excel", "open the excel", "read xlsx",
        "read the presentation", "read the powerpoint", "read pptx",
        "index documents", "index my documents", "search my documents",
        "query documents", "search documents", "find in documents",
        "list indexed", "remove indexed source",
    ],
    "cron": [
        "schedule every", "schedule a recurring", "run every day",
        "run every week", "run every hour", "run every morning",
        "every weekday", "every monday", "every friday",
        "cron job", "add cron", "list crons", "remove cron",
        "delete cron", "pause cron", "enable cron", "disable cron",
        "recurring reminder", "recurring task",
    ],
    "weather": [
        "forecast", "temperature outside", "will it rain",
        "is it raining", "rain today", "rain tomorrow", "snow today",
        "how hot outside", "how cold outside", "uv index", "sun protection",
        "what's the weather", "how's the weather",
    ],
    "web": ["search for", "search the web", "look it up", "look up", "google ", "find online",
            "look online", "browse to", "visit http", "read this article", "read the page",
            "open this url", "summarize this url", "read http", "what does this page"],
    "code": ["run this code", "execute this", "run python", "run shell", "```python", "```sh", "run the code"],
    "calendar": ["add to calendar", "schedule a", "create an event", "calendar event", "add an appointment", "add event"],
    "home": ["turn on the", "turn off the", "lights on", "lights off", "home automation", "smart home"],
    "reminder": ["set a reminder", "set reminder", "don't let me forget", "notify me when", "remind me to"],
    "network": ["mac address", "change mac", "spoof mac", "mask mac", "randomize mac",
                "restore mac", "show mac", "my mac", "fake mac", "network address"],
    "wifi": ["wifi status", "wi-fi status", "wifi network", "wi-fi network",
             "scan for wifi", "scan wifi", "nearby wifi", "nearby networks",
             "wifi interfaces", "wireless interfaces", "am i connected to wifi",
             "wifi signal", "wifi strength", "wifi channel"],
    "respond": ["set a timer", "set timer", "start a timer", "start timer", "timer for",
                "set the volume", "volume up", "volume down", "mute", "unmute",
                "system info", "how much ram", "cpu usage", "disk space",
                "make a note", "don't forget", "add a note", "my notes", "list notes",
                "show notes", "delete note", "clear notes",
                "dim the", "set brightness", "set the brightness", "lights to ",
                "play music", "play the music", "resume music", "resume playback",
                "pause music", "pause the music", "pause playback",
                "next track", "skip track", "next song", "skip song",
                "previous track", "go back a track", "previous song", "last song",
                "stop music", "stop the music", "stop playback",
                "what's playing", "what is playing", "now playing",
                "what song", "current song", "current track",
                "enable tor", "turn on tor", "start tor", "use tor", "anonymize",
                "enable vpn", "turn on vpn", "route through tor",
                "disable tor", "turn off tor", "stop tor",
                "disable vpn", "turn off vpn",
                "tor status", "vpn status", "am i anonymous", "check tor",
                "take a screenshot", "screenshot of", "capture screen", "capture my screen",
                "latest news", "recent news", "fetch news", "news about", "what's in the news",
                "rss feed", "fetch rss", "read the rss", "read rss",
                "send email", "send an email", "email to ", "write an email",
                "compose an email", "draft an email", "reply to ",
                "morning briefing", "daily briefing", "today's briefing",
                "give me a briefing", "good morning", "what's today",
                "what's on today", "what do i have today",
                "enable observer", "start observer", "disable observer", "stop observer",
                "observer status", "what am i doing", "what are you tracking"],
}


# keyword → tool name to call directly, bypassing LLM tool selection
_DIRECT_TOOL_KEYWORDS: dict[str, str] = {
    "morning briefing": "morning_briefing",
    "daily briefing": "morning_briefing",
    "today's briefing": "morning_briefing",
    "give me a briefing": "morning_briefing",
    "good morning": "morning_briefing",
    "what's today": "morning_briefing",
    "what's on today": "morning_briefing",
    "what do i have today": "morning_briefing",
    # Email
    "check my email": "list_inbox",
    "any new emails": "list_inbox",
    "any emails": "list_inbox",
    "read my inbox": "list_inbox",
    "show my inbox": "list_inbox",
    "new emails": "list_inbox",
}

_EMAIL_SEARCH_RE = re.compile(
    r"(?:search|find|look\s+(?:for|up))\s+(?:my\s+)?(?:email|emails|inbox|gmail)"
    r"\s+(?:for|about|from|with|regarding)\s+(.+)",
    re.I,
)


def _extract_email_search(text: str) -> str | None:
    m = _EMAIL_SEARCH_RE.match(text.strip())
    return m.group(1).strip().rstrip("?.") if m else None


def _keyword_route(text: str) -> str | None:
    lower = text.lower()
    for intent, keywords in _KEYWORD_ROUTES.items():
        if any(kw in lower for kw in keywords):
            return intent
    return None


def _direct_tool(text: str) -> str | None:
    lower = text.lower()
    for kw, tool_name in _DIRECT_TOOL_KEYWORDS.items():
        if kw in lower:
            return tool_name
    return None


class AgentState(TypedDict):
    messages: list[dict]
    memory_context: str
    active_agent: str | None
    search_provider: str
    hop_count: int
    tool_results: list[str]
    direct_result: str  # set by direct-tool path; respond node returns it without LLM


async def _supervisor_node(state: AgentState) -> dict:
    if state["hop_count"] >= _HOP_LIMIT:
        return {"active_agent": "respond"}

    if state["tool_results"]:
        return {"active_agent": "respond"}

    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), ""
    )

    # Fast path: email search with extracted query
    email_query = _extract_email_search(last_user)
    if email_query:
        try:
            result = await call_tool_async("search_email", {"query": email_query})
            result_str = str(result)
            await events.emit("transcript", {"role": "tool", "text": f"[search_email]\n{result_str}"})
            logger.info("Supervisor direct-called search_email query=%r", email_query)
            return {"active_agent": "respond", "direct_result": result_str, "hop_count": state["hop_count"] + 1}
        except Exception:
            logger.exception("Direct search_email call failed; falling through to LLM")

    # Fast path: directly call a known tool without LLM tool selection
    direct = _direct_tool(last_user)
    if direct:
        try:
            result = await call_tool_async(direct, {})
            result_str = str(result)
            await events.emit("transcript", {"role": "tool", "text": f"[{direct}]\n{result_str}"})
            logger.info("Supervisor direct-called tool: %s", direct)
            return {"active_agent": "respond", "direct_result": result_str, "hop_count": state["hop_count"] + 1}
        except Exception:
            logger.exception("Direct tool call %r failed; falling through to LLM", direct)

    intent = _keyword_route(last_user)
    if intent is None:
        classify_messages = [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            *state["messages"],
        ]
        msg = await call_llm(classify_messages)
        content = msg.get("content", "") or ""
        intent = content.strip().lower().split()[0] if content.strip() else "respond"
        if intent not in _KNOWN_INTENTS:
            intent = "respond"

    logger.info("Supervisor routed to: %s", intent)
    if intent != "respond":
        await events.emit("agent_routing", {"agent": intent})
    return {"active_agent": intent, "hop_count": state["hop_count"] + 1}


async def _respond_node(state: AgentState) -> dict:
    if state.get("direct_result"):
        history = list(state["messages"])
        history.append({"role": "assistant", "content": state["direct_result"]})
        return {"messages": history}

    tools = get_tool_schemas()
    history = list(state["messages"])

    context = state.get("memory_context", "")
    if context and history:
        history = [history[0], {"role": "system", "content": f"Context:\n{context}"}, *history[1:]]

    if state["tool_results"]:
        combined = "\n".join(state["tool_results"])
        history.append({"role": "system", "content": f"Agent results:\n{combined}"})
        history.append({"role": "system", "content": "Present the result above to the user exactly as provided. Do not add, expand, or replace information."})
        # Specialist already handled this — don't offer tools or LLM re-invokes them
        tools = []

    active_tools: list | None = tools or None
    for _ in range(_TOOL_CALL_LIMIT):
        payload_msg = await call_llm(history, tools=active_tools)
        history.append(payload_msg)
        if not payload_msg.get("tool_calls"):
            break
        for tc in payload_msg["tool_calls"]:
            fn = tc["function"]
            try:
                result = await call_tool_async(fn["name"], fn.get("arguments") or {})
            except ToolExecutionError as e:
                result = f"[Tool error: {e}]"
            except Exception as exc:
                result = f"Error: {exc}"
            result_str = str(result)
            await events.emit("transcript", {
                "role": "tool",
                "text": f"[{fn['name']}]\n{result_str}",
            })
            history.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result_str,
            })
        # After executing tools, guide the LLM to present results without re-invoking tools
        active_tools = None
        history.append({
            "role": "system",
            "content": "Present the tool results above to the user exactly as provided. Do not add, expand, or replace information.",
        })
    else:
        logger.warning("Tool-call limit (%d) reached; returning fallback reply", _TOOL_CALL_LIMIT)
        history.append({"role": "assistant", "content": "I reached the tool call limit and could not complete your request."})

    return {"messages": history}


def _route(state: AgentState) -> str:
    return state.get("active_agent") or "respond"


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("supervisor", _supervisor_node)
    g.add_node("memory", memory_node)
    g.add_node("web", web_node)
    g.add_node("code", code_node)
    g.add_node("calendar", calendar_node)
    g.add_node("home", home_node)
    g.add_node("reminder", reminder_node)
    g.add_node("network", network_node)
    g.add_node("wifi", wifi_node)
    g.add_node("file", file_node)
    g.add_node("weather", weather_node)
    g.add_node("respond", _respond_node)

    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", _route, {
        "memory": "memory",
        "web": "web",
        "code": "code",
        "calendar": "calendar",
        "home": "home",
        "reminder": "reminder",
        "network": "network",
        "wifi": "wifi",
        "file": "file",
        "weather": "weather",
        "cron": "respond",
        "respond": "respond",
    })
    for agent in ("memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file", "weather"):
        g.add_edge(agent, "supervisor")
    g.add_edge("respond", END)
    return g.compile()


_graph = _build_graph()


async def run_turn(messages: list[dict]) -> tuple[str, list[dict]]:
    config = get_config()
    store = get_memory_store()

    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    memory_context = "\n".join(store.recall(last_user)) if last_user else ""

    try:
        from core.observer import get_observer
        profile = get_observer().get_profile()
        if profile:
            messages = [messages[0],
                        {"role": "system", "content": f"User activity context:\n{profile}"},
                        *messages[1:]]
    except Exception:
        pass

    state = AgentState(
        messages=list(messages),
        memory_context=memory_context,
        active_agent=None,
        search_provider=config.web_search_default,
        hop_count=0,
        tool_results=[],
        direct_result="",
    )
    result = await _graph.ainvoke(state)
    final_messages = result["messages"]
    last = final_messages[-1]
    response = last.get("content", "")
    for _prefix in ("assistant\n\n", "assistant\n", "user\n\n", "user\n", "system\n\n", "system\n"):
        if response.startswith(_prefix):
            response = response[len(_prefix):]
            break

    if last_user:
        store.add_turn("user", last_user)
    if response:
        store.add_turn("assistant", response)

    from agents.chat_history import add_message
    if last_user:
        await asyncio.to_thread(add_message, "user", last_user)
    if response:
        await asyncio.to_thread(add_message, "assistant", response)


    return response, final_messages
