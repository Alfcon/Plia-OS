"""Tests for workflow step type (subworkflow composition)."""
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agents.workflow_store import run_workflow, dry_run_workflow, save_workflow


@contextmanager
def _wf_at(tmp_path: Path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


@pytest.fixture
def wf_path(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_subworkflow_called_with_interpolated_params(wf_path):
    with _wf_at(wf_path):
        save_workflow("child", steps=[
            {"step_type": "tool", "tool": "child_tool", "params": {"received": "{{payload.msg}}"}},
        ])
        save_workflow("parent", steps=[{
            "step_type": "workflow",
            "workflow_name": "child",
            "params": {"msg": "{{payload.input}}"},
        }])
        with patch("agents.workflow_store.call_tool_async", AsyncMock(return_value="child_result")) as mock_tool:
            output = await run_workflow("parent", payload={"input": "hello"})

    assert output[0]["result"] == "child_result"
    # child_tool must have received {"received": "hello"}
    mock_tool.assert_called_once_with("child_tool", {"received": "hello"})


@pytest.mark.asyncio
async def test_subworkflow_result_becomes_prev(wf_path):
    with _wf_at(wf_path):
        save_workflow("child", steps=[
            {"step_type": "tool", "tool": "ct", "params": {}},
        ])
        save_workflow("parent", steps=[
            {"step_type": "workflow", "workflow_name": "child", "params": {}},
            {"step_type": "tool", "tool": "next", "params": {"val": "{{prev}}"}},
        ])
        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=["from_child", "done"])) as mock_tool:
            output = await run_workflow("parent")

    # "next" tool must receive "from_child" as val
    next_call = mock_tool.call_args_list[1]
    assert next_call[0][1]["val"] == "from_child"
    assert output[1]["result"] == "done"


@pytest.mark.asyncio
async def test_subworkflow_recursion_guard(wf_path):
    with _wf_at(wf_path):
        save_workflow("loop", steps=[{
            "step_type": "workflow",
            "workflow_name": "loop",
            "params": {},
        }])
        output = await run_workflow("loop")

    # Workflow stops with a recursion error somewhere in the chain
    assert any(
        s.get("error") and "recursion" in s["error"].lower()
        for s in output
    )


@pytest.mark.asyncio
async def test_subworkflow_error_propagates(wf_path):
    with _wf_at(wf_path):
        save_workflow("child", steps=[
            {"step_type": "tool", "tool": "fail", "params": {}},
        ])
        save_workflow("parent", steps=[{
            "step_type": "workflow",
            "workflow_name": "child",
            "params": {},
        }])
        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=RuntimeError("child failed"))):
            output = await run_workflow("parent")

    assert output[0]["error"] is not None
    assert "child failed" in output[0]["error"]


@pytest.mark.asyncio
async def test_subworkflow_dry_run(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[{
            "step_type": "workflow",
            "workflow_name": "other",
            "params": {"k": "v"},
        }])
        output = await dry_run_workflow("w")

    assert "other" in output[0]["result"]
    assert "[DRY RUN]" in output[0]["result"]
