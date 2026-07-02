# Agent Builder Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Plia-OS workflow engine with parallel step execution, per-step error handling, and subworkflow composition.

**Architecture:** Three new step types (`parallel`, `workflow`) and two new per-step fields (`continue_on_error`, `on_error`) are added to `agents/workflow_store.py`. The dashboard UI in `dashboard/static/index.html` is extended to expose all three features. Tasks 1–3 are independent backend changes to the same file; Task 4 is the dashboard UI.

**Tech Stack:** Python 3.12, asyncio, FastAPI, vanilla JS (dashboard SPA)

## Global Constraints

- No new pip dependencies
- `import asyncio` must be added to `agents/workflow_store.py` imports (not yet present)
- `_run_step` signature unchanged: `async def _run_step(step, step_results, payload, run_vars=None) -> tuple[str, str|None, list[dict]]`
- `run_workflow` signature unchanged: `async def run_workflow(name, payload=None) -> list[dict]`
- Patch target for `call_tool_async` in tests: `"agents.workflow_store.call_tool_async"` (module-level import binding)
- `_wf_depth` ContextVar recursion guard (depth ≥ 10 → RuntimeError) already present — no additional guard needed
- Branch `sub_step_results` is always a copy of parent `step_results`; `run_vars` is always shared by reference
- Pre-existing test failures that are NOT regressions: `test_supervisor_does_not_emit_for_respond`, `test_list_sorted_newest_first` (both fixed in this session — full suite should pass)
- Run tests with: `source .venv/bin/activate && pytest <test_file> -v`
- Full suite: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: Parallel Step Type

**Files:**
- Modify: `agents/workflow_store.py` (add `import asyncio`, add `parallel` branch in `_run_step` and `dry_run_workflow`)
- Create: `tests/test_workflow_parallel.py`

**Interfaces:**
- Consumes: `_run_step`, `run_workflow`, `dry_run_workflow`, `save_workflow` (all existing)
- Produces: `parallel` step type — `run_vars[branch_name] = {"result": ..., "error": ...}` for each named branch; `{{prev}}` = `json.dumps([results_in_order])`

- [ ] **Step 1: Add `import asyncio` to `workflow_store.py`**

Open `agents/workflow_store.py`. The imports block currently starts with:
```python
from __future__ import annotations

import contextvars
import json
import os
import re
import time
from pathlib import Path
from typing import Any
```

Add `import asyncio` after `from __future__ import annotations`:
```python
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import time
from pathlib import Path
from typing import Any
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_workflow_parallel.py`:

```python
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
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_workflow_parallel.py -v
```

Expected: all 5 FAIL (parallel step type not yet implemented)

- [ ] **Step 4: Add `parallel` branch to `_run_step`**

In `agents/workflow_store.py`, find the `elif step_type == "if":` block and the `else:` block. Add a new `elif step_type == "parallel":` branch BETWEEN them:

```python
    elif step_type == "parallel":
        branches = step.get("branches", [])

        async def _run_branch(branch: dict) -> tuple[str, str, str]:
            branch_name = branch.get("name", "")
            branch_steps = branch.get("steps", [])
            sub_results = list(step_results)
            branch_prev = step_results[-1] if step_results else ""
            for sub_step in branch_steps:
                sub_result, sub_error, _ = await _run_step(sub_step, sub_results, payload, run_vars)
                sub_results.append(sub_result)
                if sub_error:
                    return branch_name, sub_result, sub_error
                branch_prev = sub_result
            return branch_name, branch_prev, ""

        gathered = await asyncio.gather(*[_run_branch(b) for b in branches], return_exceptions=True)
        results_list: list[str] = []
        for item in gathered:
            if isinstance(item, Exception):
                results_list.append(str(item))
            else:
                branch_name, branch_result, branch_error = item
                if run_vars is not None and branch_name:
                    run_vars[branch_name] = {"result": branch_result, "error": branch_error}
                results_list.append(branch_result if not branch_error else branch_error)
        return json.dumps(results_list), None, []

    else:
        return "", f"Unknown step_type: {step_type!r}", []
```

- [ ] **Step 5: Add `parallel` branch to `dry_run_workflow`**

In `dry_run_workflow`, find the `elif step_type == "if":` block and the `else:` block. Add BETWEEN them:

```python
        elif step_type == "parallel":
            branches = step.get("branches", [])
            branch_names = ", ".join(b.get("name", "?") for b in branches)
            dry_result = f"[DRY RUN] parallel: {len(branches)} branches ({branch_names})"
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_workflow_parallel.py -v
```

Expected: all 5 PASS

- [ ] **Step 7: Run full suite to check no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass (no new failures)

- [ ] **Step 8: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_parallel.py
git commit -m "feat(workflow): add parallel step type with concurrent branch execution"
```

---

### Task 2: Error Handling (`continue_on_error` + `on_error`)

**Files:**
- Modify: `agents/workflow_store.py` (restructure error handling in `run_workflow`)
- Create: `tests/test_workflow_error_handling.py`

**Interfaces:**
- Consumes: `_run_step`, `run_workflow` (existing); Task 1's parallel step (already in file)
- Produces: per-step `continue_on_error: true` flag; per-step `on_error: [{...steps...}]` list; both available on any step type

**Key change:** In `run_workflow`, the error-handling block currently reads:
```python
            if error:
                break
```
This must be restructured to check `on_error` and `continue_on_error` BEFORE the `step_results.append` and `output.append` calls, so the appended values reflect the fallback result.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflow_error_handling.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_workflow_error_handling.py -v
```

Expected: test 1 FAIL (workflow stops), tests 2-5 FAIL

- [ ] **Step 3: Restructure the error-handling block in `run_workflow`**

In `agents/workflow_store.py`, find the `run_workflow` function. The current inner loop body is:

```python
        for i, step in enumerate(wf["steps"]):
            note = step.get("note", "")
            step_type = step.get("step_type", "tool")
            t0 = time.monotonic()
            try:
                result_str, error, sub_steps = await _run_step(step, step_results, payload, run_vars)
            except Exception as exc:
                result_str = ""
                error = str(exc)
                sub_steps = []
            duration_ms = int((time.monotonic() - t0) * 1000)
            step_results.append(result_str)
            if step_name := step.get("name"):
                run_vars[step_name] = {
                    "result": result_str,
                    "error": error or "",
                }
            output.append({
                "step": i,
                "step_type": step_type,
                "tool": step.get("tool", ""),
                "params": step.get("params", {}),
                "note": note,
                "result": result_str,
                "error": error,
                "duration_ms": duration_ms,
                "sub_steps": sub_steps,
            })
            if error:
                break
```

Replace it with:

```python
        for i, step in enumerate(wf["steps"]):
            note = step.get("note", "")
            step_type = step.get("step_type", "tool")
            t0 = time.monotonic()
            try:
                result_str, error, sub_steps = await _run_step(step, step_results, payload, run_vars)
            except Exception as exc:
                result_str = ""
                error = str(exc)
                sub_steps = []

            # Error handling: on_error fallback, then continue_on_error
            if error:
                on_error_steps = step.get("on_error")
                if on_error_steps:
                    fallback_results = list(step_results)
                    fallback_prev = ""
                    fallback_error: str | None = error
                    for fb_step in on_error_steps:
                        try:
                            fb_result, fb_err, _ = await _run_step(fb_step, fallback_results, payload, run_vars)
                        except Exception as exc:
                            fallback_error = str(exc)
                            break
                        fallback_results.append(fb_result)
                        if fb_err:
                            fallback_error = fb_err
                            break
                        fallback_prev = fb_result
                        fallback_error = None
                    result_str = fallback_prev
                    error = fallback_error

            duration_ms = int((time.monotonic() - t0) * 1000)
            step_results.append(result_str)
            if step_name := step.get("name"):
                run_vars[step_name] = {
                    "result": result_str,
                    "error": error or "",
                }
            output.append({
                "step": i,
                "step_type": step_type,
                "tool": step.get("tool", ""),
                "params": step.get("params", {}),
                "note": note,
                "result": result_str,
                "error": error,
                "duration_ms": duration_ms,
                "sub_steps": sub_steps,
            })
            if error and not step.get("continue_on_error"):
                break
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_workflow_error_handling.py -v
```

Expected: all 5 PASS

- [ ] **Step 5: Run full suite to check no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_error_handling.py
git commit -m "feat(workflow): add continue_on_error and on_error fallback per-step error handling"
```

---

### Task 3: Subworkflow Step Type

**Files:**
- Modify: `agents/workflow_store.py` (add `workflow` branch in `_run_step` and `dry_run_workflow`)
- Create: `tests/test_workflow_subworkflow.py`

**Interfaces:**
- Consumes: `_run_step`, `run_workflow`, `dry_run_workflow`, `_interpolate_params` (existing); `_wf_depth` ContextVar recursion guard (existing, already protects against infinite recursion)
- Produces: `workflow` step type — calls `run_workflow(workflow_name, payload=interpolated_params)`; result = child's last step result; error = child's last step error or recursion limit message

**Note on `agent` step type vs `workflow` step type:** The existing `agent` step type (line ~147) uses `step.get("name", "")` for the agent slug AND as the step variable name. This is a pre-existing design choice. The new `workflow` step type uses `step.get("workflow_name", "")` for the child workflow name and `step.get("name", "")` for the step variable name — the two are separate fields.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflow_subworkflow.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_workflow_subworkflow.py -v
```

Expected: all 5 FAIL (workflow step type not yet implemented)

- [ ] **Step 3: Add `workflow` branch to `_run_step`**

In `agents/workflow_store.py`, find the `elif step_type == "parallel":` block (added in Task 1) and the `else:` block. Add BETWEEN them:

```python
    elif step_type == "workflow":
        wf_name = step.get("workflow_name", "")
        params = _interpolate_params(step.get("params", {}), step_results, payload, run_vars)
        child_output = await run_workflow(wf_name, payload=params)
        if not child_output:
            return "", "Subworkflow returned no output", []
        last = child_output[-1]
        if last.get("error"):
            return last.get("result", ""), last["error"], []
        return last.get("result", ""), None, []
```

- [ ] **Step 4: Add `workflow` branch to `dry_run_workflow`**

In `dry_run_workflow`, find the `elif step_type == "parallel":` block (added in Task 1) and the `else:` block. Add BETWEEN them:

```python
        elif step_type == "workflow":
            wf_name = step.get("workflow_name", "")
            params = _interpolate_params(step.get("params", {}), step_results, payload, run_vars)
            dry_result = f"[DRY RUN] would call workflow {wf_name!r} with {params}"
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_workflow_subworkflow.py -v
```

Expected: all 5 PASS

- [ ] **Step 6: Run full suite to check no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_subworkflow.py
git commit -m "feat(workflow): add workflow step type for subworkflow composition"
```

---

### Task 4: Dashboard UI

**Files:**
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes: Tasks 1–3 backend (new step types and fields now accepted by the API)
- Produces: UI for parallel step (branch editor), error-handling inputs on all steps, subworkflow step fields; all wired into existing `_wfCollectSteps()` and `wfLoad()` functions

**Context:** `dashboard/static/index.html` is a large self-contained SPA. The workflow builder creates step cards dynamically. Each step card has:
- A step-name input (`.wf-step-name`, added in Phase 3)
- A step-type `<select>` with options: `tool`, `llm`, `agent`, `if`
- Type-specific field divs: `.wf-tool-fields`, `.wf-llm-fields`, `.wf-agent-fields`, `.wf-if-fields`
- `_wfStepTypeChanged(sel)` shows/hides field divs when type changes
- `_wfCollectSteps()` serializes all cards to a step JSON array
- `wfLoad(wf)` populates cards from a saved workflow's steps
- `wfNew()` resets the form

Read `dashboard/static/index.html` before implementing — find the existing step card template in `wfAddStep`, the `_wfStepTypeChanged` function, `_wfCollectSteps`, and `wfLoad`.

- [ ] **Step 1: Add `parallel` and `workflow` options to the step-type select**

Find the `<select>` element inside `wfAddStep` that creates the step-type dropdown. It currently has options for `tool`, `llm`, `agent`, `if`. Add:

```html
<option value="parallel">Parallel branches</option>
<option value="workflow">Subworkflow</option>
```

- [ ] **Step 2: Add `.wf-parallel-fields` div to the step card template**

Inside `wfAddStep`, after the `.wf-if-fields` div, add:

```html
<div class="wf-parallel-fields" style="display:none">
  <div class="wf-parallel-branches"></div>
  <button type="button" onclick="_wfAddBranch(this)" style="margin-top:4px">+ Add Branch</button>
</div>
```

- [ ] **Step 3: Add `.wf-workflow-fields` div to the step card template**

After the `.wf-parallel-fields` div, add:

```html
<div class="wf-workflow-fields" style="display:none">
  <input class="wf-workflow-name" placeholder="Workflow name" style="width:100%;margin-bottom:4px">
  <label style="font-size:0.85em">Params (JSON object):</label>
  <textarea class="wf-workflow-params" rows="3" placeholder='{"key": "{{prev}}"}' style="width:100%;font-family:monospace;font-size:0.85em"></textarea>
</div>
```

- [ ] **Step 4: Add error-handling inputs to the step card template**

After `.wf-workflow-fields` and before the note field (`.wf-note`), add to every step card:

```html
<div class="wf-error-fields" style="margin-top:6px">
  <label style="font-size:0.85em"><input type="checkbox" class="wf-continue-on-error"> Continue on error</label>
  <br>
  <label style="font-size:0.85em">On error (JSON step array):</label>
  <textarea class="wf-on-error" rows="2" placeholder='[{"step_type":"llm","prompt":"Fallback: {{prev}}"}]' style="width:100%;font-family:monospace;font-size:0.85em"></textarea>
</div>
```

- [ ] **Step 5: Add `_wfAddBranch` helper function**

Add a new JS function near the other workflow helper functions:

```javascript
function _wfAddBranch(btn) {
  const container = btn.previousElementSibling; // .wf-parallel-branches
  const idx = container.children.length;
  const div = document.createElement('div');
  div.style.cssText = 'border:1px solid #444;padding:4px;margin-top:4px';
  div.innerHTML = `
    <input class="wf-branch-name" placeholder="Branch name" style="width:100%;margin-bottom:2px">
    <label style="font-size:0.85em">Steps (JSON array):</label>
    <textarea class="wf-branch-steps" rows="3" placeholder='[{"step_type":"tool","tool":"search_web","params":{}}]' style="width:100%;font-family:monospace;font-size:0.85em"></textarea>
    <button type="button" onclick="this.parentElement.remove()" style="font-size:0.8em;margin-top:2px">Remove branch</button>
  `;
  container.appendChild(div);
  _wfUpdateVarPicker();
}
```

- [ ] **Step 6: Update `_wfStepTypeChanged` to handle `parallel` and `workflow`**

Find `_wfStepTypeChanged(sel)`. It currently shows/hides `.wf-tool-fields`, `.wf-llm-fields`, `.wf-agent-fields`, `.wf-if-fields`. Extend it to also hide/show `.wf-parallel-fields` and `.wf-workflow-fields`:

```javascript
function _wfStepTypeChanged(sel) {
  const card = sel.closest('[data-step-idx]');
  const t = sel.value;
  card.querySelector('.wf-tool-fields').style.display     = t === 'tool'     ? '' : 'none';
  card.querySelector('.wf-llm-fields').style.display      = t === 'llm'      ? '' : 'none';
  card.querySelector('.wf-agent-fields').style.display    = t === 'agent'    ? '' : 'none';
  card.querySelector('.wf-if-fields').style.display       = t === 'if'       ? '' : 'none';
  card.querySelector('.wf-parallel-fields').style.display = t === 'parallel' ? '' : 'none';
  card.querySelector('.wf-workflow-fields').style.display = t === 'workflow'  ? '' : 'none';
  // step-name input: hide for agent (agent slug uses name differently)
  const nameRow = card.querySelector('.wf-step-name');
  if (nameRow) nameRow.style.display = t === 'agent' ? 'none' : '';
  _wfUpdateVarPicker();
}
```

- [ ] **Step 7: Update `_wfCollectSteps` to serialize the new fields**

Find `_wfCollectSteps()`. It currently serializes tool, llm, agent, and if steps. Add cases for `parallel` and `workflow`, and add `continue_on_error`/`on_error` to every step:

For the `parallel` case (add after the `if` case):
```javascript
    } else if (type === 'parallel') {
      const branchDivs = card.querySelectorAll('.wf-parallel-branches > div');
      step.branches = Array.from(branchDivs).map(div => ({
        name: div.querySelector('.wf-branch-name').value.trim(),
        steps: (() => { try { return JSON.parse(div.querySelector('.wf-branch-steps').value || '[]'); } catch { return []; } })(),
      }));
```

For the `workflow` case:
```javascript
    } else if (type === 'workflow') {
      step.workflow_name = card.querySelector('.wf-workflow-name').value.trim();
      try { step.params = JSON.parse(card.querySelector('.wf-workflow-params').value || '{}'); } catch { step.params = {}; }
```

For error handling (add to EVERY step, after the type-specific fields are set):
```javascript
    // Error handling fields (all step types)
    if (card.querySelector('.wf-continue-on-error').checked) {
      step.continue_on_error = true;
    }
    const onErrVal = card.querySelector('.wf-on-error').value.trim();
    if (onErrVal) {
      try { step.on_error = JSON.parse(onErrVal); } catch { /* invalid JSON, skip */ }
    }
```

- [ ] **Step 8: Update `wfLoad` to populate the new fields**

Find `wfLoad(wf)`. It currently populates tool, llm, agent, and if step cards. Add population for `parallel`, `workflow`, and error-handling fields:

For `parallel` (add after the `if` case):
```javascript
      } else if (s.step_type === 'parallel') {
        card.querySelector('.wf-step-type').value = 'parallel';
        _wfStepTypeChanged(card.querySelector('.wf-step-type'));
        const container = card.querySelector('.wf-parallel-branches');
        (s.branches || []).forEach(branch => {
          _wfAddBranch(card.querySelector('[onclick="_wfAddBranch(this)"]'));
          const branchDiv = container.lastElementChild;
          branchDiv.querySelector('.wf-branch-name').value = branch.name || '';
          branchDiv.querySelector('.wf-branch-steps').value = JSON.stringify(branch.steps || [], null, 2);
        });
```

For `workflow`:
```javascript
      } else if (s.step_type === 'workflow') {
        card.querySelector('.wf-step-type').value = 'workflow';
        _wfStepTypeChanged(card.querySelector('.wf-step-type'));
        card.querySelector('.wf-workflow-name').value = s.workflow_name || '';
        if (s.params) card.querySelector('.wf-workflow-params').value = JSON.stringify(s.params, null, 2);
```

For error-handling fields (add to EVERY step after type-specific population):
```javascript
      // Error handling
      if (s.continue_on_error) card.querySelector('.wf-continue-on-error').checked = true;
      if (s.on_error) card.querySelector('.wf-on-error').value = JSON.stringify(s.on_error, null, 2);
```

- [ ] **Step 9: Run full suite to check no regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass (no backend changes in this task)

- [ ] **Step 10: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add parallel, subworkflow, and error-handling step UI"
```
