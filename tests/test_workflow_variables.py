from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch, call


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


def test_interpolate_steps_result():
    from agents.workflow_store import _interpolate
    run_vars = {"fetch": {"result": "hello", "error": ""}}
    result = _interpolate("Got: {{steps.fetch.result}}", [], run_vars=run_vars)
    assert result == "Got: hello"


def test_interpolate_steps_error():
    from agents.workflow_store import _interpolate
    run_vars = {"step1": {"result": "", "error": "boom"}}
    result = _interpolate("Err: {{steps.step1.error}}", [], run_vars=run_vars)
    assert result == "Err: boom"


@pytest.mark.asyncio
async def test_named_step_result_accessible_in_later_step(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"name": "fetch", "step_type": "tool", "tool": "t1", "params": {}},
        {"step_type": "tool", "tool": "t2", "params": {"q": "{{steps.fetch.result}}"}},
    ])
    call_mock = AsyncMock(side_effect=["first_result", "ok"])
    with patch("agents.workflow_store.call_tool_async", call_mock):
        await run_workflow("w")
    assert call_mock.call_args_list[1] == call("t2", {"q": "first_result"})


@pytest.mark.asyncio
async def test_prev_still_works_for_unnamed_steps(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"step_type": "tool", "tool": "t1", "params": {}},
        {"step_type": "tool", "tool": "t2", "params": {"q": "{{prev}}"}},
    ])
    call_mock = AsyncMock(side_effect=["first", "second"])
    with patch("agents.workflow_store.call_tool_async", call_mock):
        output = await run_workflow("w")
    assert call_mock.call_args_list[1] == call("t2", {"q": "first"})
    assert output[1]["result"] == "second"
