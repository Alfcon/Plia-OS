from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


@pytest.mark.asyncio
async def test_llm_step_calls_llm(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [{"step_type": "llm", "prompt": "Say hi"}])
    mock_llm = AsyncMock(return_value={"content": "Hello"})
    with patch("agents.llm.call_llm", mock_llm):
        output = await run_workflow("w")
    assert output[0]["result"] == "Hello"
    assert output[0]["step_type"] == "llm"
    assert output[0]["error"] is None
    msgs = mock_llm.call_args[0][0]
    assert msgs[-1]["content"] == "Say hi"


@pytest.mark.asyncio
async def test_llm_step_uses_system_field(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [{"step_type": "llm", "prompt": "hi", "system": "Be terse."}])
    mock_llm = AsyncMock(return_value={"content": "ok"})
    with patch("agents.llm.call_llm", mock_llm):
        await run_workflow("w")
    msgs = mock_llm.call_args[0][0]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "Be terse."
    assert msgs[1]["role"] == "user"


@pytest.mark.asyncio
async def test_llm_step_interpolates_prev(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"tool": "echo", "params": {}, "note": ""},
        {"step_type": "llm", "prompt": "Translate: {{prev}}"},
    ])
    mock_llm = AsyncMock(return_value={"content": "monde"})
    with patch("agents.workflow_store.call_tool_async", AsyncMock(return_value="world")), \
         patch("agents.llm.call_llm", mock_llm):
        await run_workflow("w")
    sent_prompt = mock_llm.call_args[0][0][-1]["content"]
    assert "world" in sent_prompt


@pytest.mark.asyncio
async def test_agent_step_calls_custom_agent_node(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [{"step_type": "agent", "name": "finance", "message": "check AAPL"}])
    mock_node = AsyncMock(return_value={"tool_results": ["$200"]})
    with patch("agents.custom_agent.custom_agent_node", mock_node):
        output = await run_workflow("w")
    assert output[0]["result"] == "$200"
    assert output[0]["step_type"] == "agent"
    state = mock_node.call_args[0][0]
    assert state["active_agent"] == "custom:finance"
    assert state["messages"][0]["content"] == "check AAPL"


@pytest.mark.asyncio
async def test_agent_step_defaults_message_to_prev(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"tool": "noop", "params": {}, "note": ""},
        {"step_type": "agent", "name": "finance"},
    ])
    mock_node = AsyncMock(return_value={"tool_results": ["ok"]})
    with patch("agents.workflow_store.call_tool_async", AsyncMock(return_value="ctx")), \
         patch("agents.custom_agent.custom_agent_node", mock_node):
        await run_workflow("w")
    state = mock_node.call_args[0][0]
    assert state["messages"][0]["content"] == "ctx"


@pytest.mark.asyncio
async def test_tool_step_backward_compat(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [{"tool": "calculate", "params": {"expr": "2+2"}, "note": ""}])
    with patch("agents.workflow_store.call_tool_async", AsyncMock(return_value=4)):
        output = await run_workflow("w")
    assert output[0]["result"] == "4"
    assert output[0]["step_type"] == "tool"


@pytest.mark.asyncio
async def test_unknown_step_type_errors_and_stops(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"step_type": "zap"},
        {"tool": "never_called", "params": {}},
    ])
    output = await run_workflow("w")
    assert len(output) == 1
    assert output[0]["error"] is not None
    assert "Unknown step_type" in output[0]["error"]


@pytest.mark.asyncio
async def test_dry_run_llm_step(wf_path):
    from agents.workflow_store import save_workflow, dry_run_workflow
    save_workflow("w", [{"step_type": "llm", "prompt": "summarize this"}])
    output = await dry_run_workflow("w")
    assert "DRY RUN" in output[0]["result"]
    assert "LLM" in output[0]["result"]
    assert "summarize this" in output[0]["result"]


@pytest.mark.asyncio
async def test_dry_run_agent_step(wf_path):
    from agents.workflow_store import save_workflow, dry_run_workflow
    save_workflow("w", [{"step_type": "agent", "name": "finance", "message": "check"}])
    output = await dry_run_workflow("w")
    assert "DRY RUN" in output[0]["result"]
    assert "finance" in output[0]["result"]
