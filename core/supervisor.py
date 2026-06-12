from __future__ import annotations
import asyncio
import inspect
import logging
from typing import TypedDict
from langgraph.graph import StateGraph, END
from core.config import get_config
from core.registry import get_tool_schemas, call_tool
from agents.llm import call_llm
from agents.memory import memory_node
from agents.memory_store import get_memory_store
from agents.web import web_node
from core import events
from agents.code import code_node
from agents.calendar import calendar_node
from agents.home import home_node

logger = logging.getLogger(__name__)

_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home"}
_HOP_LIMIT = 5
_TOOL_CALL_LIMIT = 10

_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home. "
    "If the request needs no specialist, output: respond."
)


class AgentState(TypedDict):
    messages: list[dict]
    memory_context: str
    active_agent: str | None
    search_provider: str
    hop_count: int
    tool_results: list[str]


async def _supervisor_node(state: AgentState) -> dict:
    if state["hop_count"] >= _HOP_LIMIT:
        return {"active_agent": "respond"}

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
    tools = get_tool_schemas()
    history = list(state["messages"])

    context = state.get("memory_context", "")
    if context and history:
        history = [history[0], {"role": "system", "content": f"Context:\n{context}"}, *history[1:]]

    if state["tool_results"]:
        combined = "\n".join(state["tool_results"])
        history.append({"role": "system", "content": f"Agent results:\n{combined}"})

    for _ in range(_TOOL_CALL_LIMIT):
        payload_msg = await call_llm(history, tools=tools or None)
        history.append(payload_msg)
        if not payload_msg.get("tool_calls"):
            break
        for tc in payload_msg["tool_calls"]:
            fn = tc["function"]
            try:
                result = call_tool(fn["name"], fn.get("arguments") or {})
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                result = f"Error: {exc}"
            history.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result),
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
    g.add_node("respond", _respond_node)

    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", _route, {
        "memory": "memory",
        "web": "web",
        "code": "code",
        "calendar": "calendar",
        "home": "home",
        "respond": "respond",
    })
    for agent in ("memory", "web", "code", "calendar", "home"):
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

    state = AgentState(
        messages=list(messages),
        memory_context=memory_context,
        active_agent=None,
        search_provider=config.web_search_default,
        hop_count=0,
        tool_results=[],
    )
    result = await _graph.ainvoke(state)
    final_messages = result["messages"]
    last = final_messages[-1]
    response = last.get("content", "")

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
