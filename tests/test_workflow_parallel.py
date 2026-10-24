"""Tests for parallel step type in workflow engine."""
import asyncio
import json
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
async def test_parallel_all_branches_complete(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[{
            "step_type": "parallel",
            "branches": [
                {"name": "a", "steps": [{"step_type": "tool", "tool": "t1", "params": {}}]},
                {"name": "b", "steps": [{"step_type": "tool", "tool": "t2", "params": {}}]},
            ],
        }])
        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=["result_a", "result_b"])):
            output = await run_workflow("w")
    result = json.loads(output[0]["result"])
    assert result == ["result_a", "result_b"]
    assert output[0]["error"] is None


@pytest.mark.asyncio
async def test_parallel_branch_error_captured_not_fatal(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[
            {
                "step_type": "parallel",
                "branches": [
                    {"name": "ok", "steps": [{"step_type": "tool", "tool": "t1", "params": {}}]},
                    {"name": "bad", "steps": [{"step_type": "tool", "tool": "t2", "params": {}}]},
                ],
            },
            {"step_type": "tool", "tool": "t3", "params": {}},
        ])

        async def _side(tool, params):
            if tool == "t2":
                raise RuntimeError("boom")
            return "ok"

        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_side)):
            output = await run_workflow("w")

    assert len(output) == 2  # workflow continued past parallel step
    results = json.loads(output[0]["result"])
    assert results[0] == "ok"
    assert "boom" in results[1]
    assert output[0]["error"] is None  # parallel step itself has no error


@pytest.mark.asyncio
async def test_parallel_branch_results_in_run_vars(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[
            {
                "step_type": "parallel",
                "branches": [
                    {"name": "weather", "steps": [{"step_type": "tool", "tool": "t1", "params": {}}]},
                    {"name": "news", "steps": [{"step_type": "tool", "tool": "t2", "params": {}}]},
                ],
            },
            {"step_type": "tool", "tool": "t3", "params": {"msg": "{{steps.weather.result}}"}},
        ])
        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=["sunny", "top_story", "done"])) as mock_tool:
            await run_workflow("w")

    # t3 must receive "sunny" (weather branch result) as msg
    call_args = mock_tool.call_args_list[2]
    assert call_args[0][1]["msg"] == "sunny"


@pytest.mark.asyncio
async def test_parallel_branches_run_concurrently(wf_path):
    started: list[str] = []
    barrier = asyncio.Event()

    async def _slow_tool(tool, params):
        started.append(tool)
        if len(started) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=2.0)
        return f"done_{tool}"

    with _wf_at(wf_path):
        save_workflow("w", steps=[{
            "step_type": "parallel",
            "branches": [
                {"name": "a", "steps": [{"step_type": "tool", "tool": "t1", "params": {}}]},
                {"name": "b", "steps": [{"step_type": "tool", "tool": "t2", "params": {}}]},
            ],
        }])
        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_slow_tool)):
            output = await run_workflow("w")

    # barrier was set (both started before either finished)
    assert barrier.is_set()
    result = json.loads(output[0]["result"])
    assert len(result) == 2


@pytest.mark.asyncio
async def test_parallel_dry_run(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[{
            "step_type": "parallel",
            "branches": [
                {"name": "alpha", "steps": []},
                {"name": "beta", "steps": []},
            ],
        }])
        output = await dry_run_workflow("w")

    assert "parallel" in output[0]["result"]
    assert "alpha" in output[0]["result"]
    assert "beta" in output[0]["result"]
    assert "2" in output[0]["result"]
