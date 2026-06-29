from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch, call


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


def test_evaluate_condition_ops():
    from agents.workflow_store import _evaluate_condition
    assert _evaluate_condition({"op": "eq", "value": "hi"}, "hi") is True
    assert _evaluate_condition({"op": "eq", "value": "hi"}, "bye") is False
    assert _evaluate_condition({"op": "ne", "value": "a"}, "b") is True
    assert _evaluate_condition({"op": "contains", "value": "ell"}, "hello") is True
    assert _evaluate_condition({"op": "not_contains", "value": "ell"}, "world") is True
    assert _evaluate_condition({"op": "empty"}, "") is True
    assert _evaluate_condition({"op": "empty"}, "x") is False
    assert _evaluate_condition({"op": "not_empty"}, "x") is True
    assert _evaluate_condition({"op": "not_empty"}, "") is False


@pytest.mark.asyncio
async def test_if_true_branch_runs_then(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"step_type": "tool", "tool": "t1", "params": {}},
        {
            "step_type": "if",
            "condition": {"op": "contains", "value": "hello"},
            "then": [{"step_type": "tool", "tool": "t_yes", "params": {}}],
            "else": [{"step_type": "tool", "tool": "t_no", "params": {}}],
        },
    ])
    with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=["hello world", "yes_result"])):
        output = await run_workflow("w")
    assert output[-1]["result"] == "yes_result"


@pytest.mark.asyncio
async def test_if_false_branch_runs_else(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"step_type": "tool", "tool": "t1", "params": {}},
        {
            "step_type": "if",
            "condition": {"op": "contains", "value": "hello"},
            "then": [{"step_type": "tool", "tool": "t_yes", "params": {}}],
            "else": [{"step_type": "tool", "tool": "t_no", "params": {}}],
        },
    ])
    with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=["goodbye", "no_result"])):
        output = await run_workflow("w")
    assert output[-1]["result"] == "no_result"


@pytest.mark.asyncio
async def test_if_no_else_returns_prev_unchanged(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"step_type": "tool", "tool": "t1", "params": {}},
        {
            "step_type": "if",
            "condition": {"op": "eq", "value": "nomatch"},
            "then": [{"step_type": "tool", "tool": "t_yes", "params": {}}],
        },
    ])
    with patch("agents.workflow_store.call_tool_async", AsyncMock(return_value="original")):
        output = await run_workflow("w")
    assert output[-1]["result"] == "original"


@pytest.mark.asyncio
async def test_branch_step_references_parent_variables(wf_path):
    from agents.workflow_store import save_workflow, run_workflow
    save_workflow("w", [
        {"name": "first", "step_type": "tool", "tool": "t1", "params": {}},
        {
            "step_type": "if",
            "condition": {"op": "not_empty"},
            "then": [
                {"step_type": "tool", "tool": "t2", "params": {"q": "{{steps.first.result}}"}},
            ],
        },
    ])
    call_mock = AsyncMock(side_effect=["parent_val", "branch_result"])
    with patch("agents.workflow_store.call_tool_async", call_mock):
        output = await run_workflow("w")
    assert call_mock.call_args_list[1] == call("t2", {"q": "parent_val"})
    assert output[-1]["result"] == "branch_result"
