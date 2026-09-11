"""Tests for continue_on_error and on_error per-step error handling."""
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agents.workflow_store import run_workflow, save_workflow


@contextmanager
def _wf_at(tmp_path: Path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


@pytest.fixture
def wf_path(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_continue_on_error_continues_workflow(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[
            {"step_type": "tool", "tool": "fail", "params": {}, "continue_on_error": True},
            {"step_type": "tool", "tool": "ok", "params": {}},
        ])

        async def _side(tool, params):
            if tool == "fail":
                raise RuntimeError("oops")
            return "success"

        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_side)):
            output = await run_workflow("w")

    assert len(output) == 2  # workflow continued
    assert "oops" in output[0]["result"]  # error string becomes {{prev}}
    assert output[1]["result"] == "success"


@pytest.mark.asyncio
async def test_on_error_fallback_runs_and_replaces_result(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[{
            "step_type": "tool",
            "tool": "fail",
            "params": {},
            "on_error": [{"step_type": "tool", "tool": "fallback", "params": {}}],
        }])

        async def _side(tool, params):
            if tool == "fail":
                raise RuntimeError("oops")
            return "fallback_result"

        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_side)):
            output = await run_workflow("w")

    assert output[0]["result"] == "fallback_result"
    assert output[0]["error"] is None


@pytest.mark.asyncio
async def test_on_error_fallback_result_stored_in_run_vars(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[
            {
                "step_type": "tool",
                "tool": "fail",
                "params": {},
                "name": "step1",
                "on_error": [{"step_type": "tool", "tool": "fallback", "params": {}}],
            },
            {"step_type": "tool", "tool": "next", "params": {"val": "{{steps.step1.result}}"}},
        ])

        async def _side(tool, params):
            if tool == "fail":
                raise RuntimeError("oops")
            if tool == "fallback":
                return "recovered"
            return "done"

        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_side)) as mock_tool:
            await run_workflow("w")

    # "next" tool must have received "recovered" (fallback result) as val
    next_call = mock_tool.call_args_list[-1]
    assert next_call[0][1]["val"] == "recovered"


@pytest.mark.asyncio
async def test_no_flags_stops_on_error(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[
            {"step_type": "tool", "tool": "fail", "params": {}},
            {"step_type": "tool", "tool": "ok", "params": {}},
        ])

        async def _side(tool, params):
            if tool == "fail":
                raise RuntimeError("stop")
            return "should_not_reach"

        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_side)):
            output = await run_workflow("w")

    assert len(output) == 1  # stopped after first step
    assert output[0]["error"] is not None


@pytest.mark.asyncio
async def test_both_flags_on_error_runs_fallback_then_continues(wf_path):
    with _wf_at(wf_path):
        save_workflow("w", steps=[
            {
                "step_type": "tool",
                "tool": "fail",
                "params": {},
                "continue_on_error": True,
                "on_error": [{"step_type": "tool", "tool": "fallback", "params": {}}],
            },
            {"step_type": "tool", "tool": "next", "params": {}},
        ])

        async def _side(tool, params):
            if tool == "fail":
                raise RuntimeError("oops")
            return "ok"

        with patch("agents.workflow_store.call_tool_async", AsyncMock(side_effect=_side)):
            output = await run_workflow("w")

    assert len(output) == 2
    assert output[0]["result"] == "ok"  # fallback result, not error string
    assert output[0]["error"] is None
