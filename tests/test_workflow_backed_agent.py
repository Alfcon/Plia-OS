from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
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
        workflow_name=None,
    )
    defaults.update(kwargs)
    return AgentDef(**defaults)


@pytest.fixture()
def mock_store(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield


@pytest.mark.asyncio
async def test_workflow_name_routes_to_run_workflow(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(workflow_name="my-wf"))
    mock_run = AsyncMock(return_value=[{"result": "workflow output", "error": None}])
    with patch("agents.workflow_store.run_workflow", mock_run):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == ["workflow output"]
    mock_run.assert_called_once_with("my-wf", payload={"message": "what is AAPL stock"})


@pytest.mark.asyncio
async def test_workflow_error_surfaced(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(workflow_name="bad-wf"))
    mock_run = AsyncMock(return_value=[{"result": "", "error": "tool not found"}])
    with patch("agents.workflow_store.run_workflow", mock_run):
        result = await custom_agent_node(_state("custom:finance"))
    assert "Workflow error" in result["tool_results"][0]


@pytest.mark.asyncio
async def test_no_workflow_name_uses_llm(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(workflow_name=None))
    mock_llm = AsyncMock(return_value={"content": "result"})
    with patch("agents.llm.call_llm", mock_llm):
        result = await custom_agent_node(_state("custom:finance"))
    mock_llm.assert_called_once()
    assert result["tool_results"] == ["result"]


@pytest.mark.asyncio
async def test_empty_workflow_output(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(workflow_name="empty-wf"))
    with patch("agents.workflow_store.run_workflow", AsyncMock(return_value=[])):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == [""]


@pytest.mark.asyncio
async def test_missing_workflow_returns_error(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(workflow_name="missing-wf"))
    with patch("agents.workflow_store.run_workflow", AsyncMock(side_effect=KeyError("missing-wf"))):
        result = await custom_agent_node(_state("custom:finance"))
    assert "not found" in result["tool_results"][0]
