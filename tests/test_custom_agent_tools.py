from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch, call
from agents.custom_agent import _TOOL_CALL_LIMIT


def make_state(agent_name="myagent", messages=None):
    return {
        "active_agent": f"custom:{agent_name}",
        "messages": messages or [{"role": "user", "content": "hello"}],
        "memory_context": "",
        "search_provider": "ddg",
        "hop_count": 0,
        "tool_results": [],
        "direct_result": "",
    }


@pytest.mark.asyncio
async def test_tool_call_executes_and_returns_result():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="myagent", display_name="", system_prompt="You help", tool_names=["my_tool"], keywords=[], llm_description="")
    llm_seq = [
        {"tool_calls": [{"function": {"name": "my_tool", "arguments": {}}, "id": "c1"}]},
        {"content": "Done!"},
    ]
    with patch("agents.custom_agent.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(side_effect=llm_seq)), \
         patch("core.registry.call_tool_async", AsyncMock(return_value="tool result")):
        result = await custom_agent_node(make_state())
    assert result["tool_results"] == ["Done!"]


@pytest.mark.asyncio
async def test_multi_turn_tool_loop():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="myagent", display_name="", system_prompt="You help", tool_names=["t1"], keywords=[], llm_description="")
    llm_seq = [
        {"tool_calls": [{"function": {"name": "t1", "arguments": {}}, "id": "c1"}]},
        {"tool_calls": [{"function": {"name": "t1", "arguments": {}}, "id": "c2"}]},
        {"content": "All done"},
    ]
    tool_mock = AsyncMock(return_value="r")
    with patch("agents.custom_agent.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(side_effect=llm_seq)), \
         patch("core.registry.call_tool_async", tool_mock):
        result = await custom_agent_node(make_state())
    assert result["tool_results"] == ["All done"]
    assert tool_mock.call_count == 2


@pytest.mark.asyncio
async def test_tool_error_continues():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="myagent", display_name="", system_prompt="", tool_names=["boom"], keywords=[], llm_description="")
    llm_seq = [
        {"tool_calls": [{"function": {"name": "boom", "arguments": {}}, "id": "c1"}]},
        {"content": "Recovered"},
    ]
    with patch("agents.custom_agent.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(side_effect=llm_seq)), \
         patch("core.registry.call_tool_async", AsyncMock(side_effect=RuntimeError("BOOM"))):
        result = await custom_agent_node(make_state())
    assert result["tool_results"] == ["Recovered"]


@pytest.mark.asyncio
async def test_no_tools_path_unchanged():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="plain", display_name="", system_prompt="You help", tool_names=[], keywords=[], llm_description="")
    with patch("agents.custom_agent.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(return_value={"content": "Plain reply"})):
        result = await custom_agent_node(make_state("plain"))
    assert result["tool_results"] == ["Plain reply"]


@pytest.mark.asyncio
async def test_tool_call_limit_returns_fallback():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="looper", display_name="", system_prompt="", tool_names=["t"], keywords=[], llm_description="")
    always_tool = {"tool_calls": [{"function": {"name": "t", "arguments": {}}, "id": "x"}]}
    with patch("agents.custom_agent.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(return_value=always_tool)), \
         patch("core.registry.call_tool_async", AsyncMock(return_value="r")):
        result = await custom_agent_node(make_state("looper"))
    assert result["tool_results"] == ["[Tool call limit reached]"]
