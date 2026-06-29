from __future__ import annotations
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from core.agent_store import AgentDef


def _state(active_agent: str, messages=None) -> dict:
    return {
        "active_agent": active_agent,
        "messages": messages or [{"role": "user", "content": "what is AAPL stock"}],
        "memory_context": "",
        "search_provider": "ddg",
        "hop_count": 1,
        "tool_results": [],
        "direct_result": "",
    }


def _defn(**kwargs) -> AgentDef:
    defaults = dict(
        name="finance",
        display_name="Finance",
        system_prompt="You are a finance specialist.",
        tool_names=["calculate"],
        keywords=["stock"],
        llm_description="Use for finance",
        enabled=True,
        created_at="",
    )
    defaults.update(kwargs)
    return AgentDef(**defaults)


@pytest.fixture()
def mock_store(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield


@pytest.mark.asyncio
async def test_node_uses_system_prompt(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn())
    mock_llm = AsyncMock(return_value={"content": "AAPL is $200"})
    with patch("agents.llm.call_llm", mock_llm):
        await custom_agent_node(_state("custom:finance"))
    call_messages = mock_llm.call_args[0][0]
    assert call_messages[0]["role"] == "system"
    assert call_messages[0]["content"] == "You are a finance specialist."


@pytest.mark.asyncio
async def test_node_filters_tools(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(tool_names=["calculate"]))
    mock_llm = AsyncMock(return_value={"content": "result"})
    fake_tools = [
        {"type": "function", "function": {"name": "calculate", "description": ""}},
        {"type": "function", "function": {"name": "web_search", "description": ""}},
    ]
    with patch("agents.llm.call_llm", mock_llm), \
         patch("core.registry.get_tool_schemas", return_value=fake_tools):
        await custom_agent_node(_state("custom:finance"))
    _, kwargs = mock_llm.call_args
    passed_tools = kwargs.get("tools") or mock_llm.call_args[0][1] if len(mock_llm.call_args[0]) > 1 else []
    assert len(passed_tools) == 1
    assert passed_tools[0]["function"]["name"] == "calculate"


@pytest.mark.asyncio
async def test_node_returns_content_in_tool_results(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn())
    with patch("agents.llm.call_llm", AsyncMock(return_value={"content": "AAPL is $200"})):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == ["AAPL is $200"]


@pytest.mark.asyncio
async def test_node_missing_agent_returns_error(mock_store):
    from agents.custom_agent import custom_agent_node
    result = await custom_agent_node(_state("custom:nonexistent"))
    assert len(result["tool_results"]) == 1
    assert "not found" in result["tool_results"][0]


@pytest.mark.asyncio
async def test_node_empty_tool_names_calls_llm_no_tools(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(tool_names=[]))
    mock_llm = AsyncMock(return_value={"content": "ok"})
    with patch("agents.llm.call_llm", mock_llm):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == ["ok"]
    _, kwargs = mock_llm.call_args
    tools_arg = kwargs.get("tools")
    assert tools_arg is None


@pytest.mark.asyncio
async def test_node_disabled_agent_returns_error(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(enabled=False))
    result = await custom_agent_node(_state("custom:finance"))
    assert "not found or disabled" in result["tool_results"][0]
