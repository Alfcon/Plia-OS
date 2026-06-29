# Agent Builder Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tool execution to custom agents, named step variables (`{{steps.name.result}}`), and `if` conditional branching to the workflow engine.

**Architecture:** Extend in place — `agents/custom_agent.py` gets a tool-call loop, `agents/workflow_store.py` gains variable tracking + `_evaluate_condition` + `if` step handling, `dashboard/static/index.html` gains step name field + `if` UI + variable picker.

**Tech Stack:** Python asyncio, FastAPI, vanilla JS (inline SPA), pytest-asyncio.

## Global Constraints

- No new pip dependencies
- `_TOOL_CALL_LIMIT = 10` in `custom_agent.py` (matches `respond_node` in `core/supervisor.py`)
- `_run_step(step, step_results, payload, run_vars=None)` — `run_vars` optional with `None` default; all callers in `run_workflow` pass it explicitly
- `_interpolate(value, results, payload=None, run_vars=None)` — `run_vars` optional; `{{steps.name.result}}` and `{{steps.name.error}}` resolved only when `run_vars` is not None
- `_evaluate_condition` is a pure function — no I/O, no LLM calls
- `run_vars: dict[str, dict]` is passed by reference; branch steps inside `if` share the parent scope (intentional — branch steps can produce named outputs visible to main flow)
- `then`/`else` branch step lists in the `if` step UI are raw JSON textareas (no recursive builder)
- Existing tests (`test_workflow_store_steps.py`, `test_workflow_backed_agent.py`, `test_custom_agent_routing.py`, etc.) must all still pass
- All tests use project convention: `AsyncClient(transport=ASGITransport(app=create_app()))` for API tests; direct imports for unit tests
- Mock `call_llm` via `patch("agents.llm.call_llm")`; mock `call_tool_async` via `patch("core.registry.call_tool_async")`
- Workflow store tests patch `agents.workflow_store._workflows_path`
- `reset_events` autouse fixture clears event subscribers before/after each test

---

## File Map

| File | Change |
|------|--------|
| `agents/custom_agent.py` | Add `_TOOL_CALL_LIMIT = 10`; replace one-shot LLM call with tool-call loop |
| `agents/workflow_store.py` | Add `run_vars` param to `_interpolate`, `_interpolate_params`, `_run_step`; add `_evaluate_condition`; add `if` branch in `_run_step`; update `run_workflow` + `dry_run_workflow` |
| `dashboard/static/index.html` | Step name field; `if` step type + condition UI; variable picker |
| `tests/test_custom_agent_tools.py` | NEW — 5 tests |
| `tests/test_workflow_variables.py` | NEW — 4 tests |
| `tests/test_workflow_if.py` | NEW — 5 tests |

---

### Task 1: Tool execution in custom agents

**Files:**
- Modify: `agents/custom_agent.py`
- Create: `tests/test_custom_agent_tools.py`

**Interfaces:**
- Consumes: `core.registry.call_tool_async(name: str, arguments: dict) -> Any` (already imported via `import core.registry`)
- Consumes: `agents.llm.call_llm(messages, tools=None)` (already imported via `import agents.llm`)
- Produces: `_TOOL_CALL_LIMIT: int = 10` (module-level constant)

**Current state of `agents/custom_agent.py` LLM path (lines 35–45):**
```python
    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    all_tools = core.registry.get_tool_schemas()
    tools = [t for t in all_tools if t["function"]["name"] in defn.tool_names]
    msg = await agents.llm.call_llm(messages, tools=tools or None)
    content = msg.get("content") or ""
    if not content and msg.get("tool_calls"):
        content = "[Custom agent attempted a tool call but tool execution is not yet supported in Phase 1.]"
    return {"tool_results": [content]}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_custom_agent_tools.py`:

```python
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
    defn = AgentDef(name="myagent", system_prompt="You help", tool_names=["my_tool"])
    llm_seq = [
        {"tool_calls": [{"function": {"name": "my_tool", "arguments": {}}, "id": "c1"}]},
        {"content": "Done!"},
    ]
    with patch("core.agent_store.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(side_effect=llm_seq)), \
         patch("core.registry.call_tool_async", AsyncMock(return_value="tool result")):
        result = await custom_agent_node(make_state())
    assert result["tool_results"] == ["Done!"]


@pytest.mark.asyncio
async def test_multi_turn_tool_loop():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="myagent", system_prompt="You help", tool_names=["t1"])
    llm_seq = [
        {"tool_calls": [{"function": {"name": "t1", "arguments": {}}, "id": "c1"}]},
        {"tool_calls": [{"function": {"name": "t1", "arguments": {}}, "id": "c2"}]},
        {"content": "All done"},
    ]
    tool_mock = AsyncMock(return_value="r")
    with patch("core.agent_store.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(side_effect=llm_seq)), \
         patch("core.registry.call_tool_async", tool_mock):
        result = await custom_agent_node(make_state())
    assert result["tool_results"] == ["All done"]
    assert tool_mock.call_count == 2


@pytest.mark.asyncio
async def test_tool_error_continues():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="myagent", system_prompt="", tool_names=["boom"])
    llm_seq = [
        {"tool_calls": [{"function": {"name": "boom", "arguments": {}}, "id": "c1"}]},
        {"content": "Recovered"},
    ]
    with patch("core.agent_store.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(side_effect=llm_seq)), \
         patch("core.registry.call_tool_async", AsyncMock(side_effect=RuntimeError("BOOM"))):
        result = await custom_agent_node(make_state())
    assert result["tool_results"] == ["Recovered"]


@pytest.mark.asyncio
async def test_no_tools_path_unchanged():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="plain", system_prompt="You help", tool_names=[])
    with patch("core.agent_store.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(return_value={"content": "Plain reply"})):
        result = await custom_agent_node(make_state("plain"))
    assert result["tool_results"] == ["Plain reply"]


@pytest.mark.asyncio
async def test_tool_call_limit_returns_fallback():
    from core.agent_store import AgentDef
    from agents.custom_agent import custom_agent_node
    defn = AgentDef(name="looper", system_prompt="", tool_names=["t"])
    always_tool = {"tool_calls": [{"function": {"name": "t", "arguments": {}}, "id": "x"}]}
    with patch("core.agent_store.get_agent", return_value=defn), \
         patch("agents.llm.call_llm", AsyncMock(return_value=always_tool)), \
         patch("core.registry.call_tool_async", AsyncMock(return_value="r")):
        result = await custom_agent_node(make_state("looper"))
    assert result["tool_results"] == ["[Tool call limit reached]"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate
pytest tests/test_custom_agent_tools.py -v --tb=short
```
Expected: 5 failures (`ImportError: cannot import name '_TOOL_CALL_LIMIT'` and similar).

- [ ] **Step 3: Add `_TOOL_CALL_LIMIT` and replace the LLM stub**

In `agents/custom_agent.py`, add at module level (after imports, before `logger = ...`):
```python
_TOOL_CALL_LIMIT = 10
```

Replace the existing LLM path (the 10 lines starting with `messages = [` through `return {"tool_results": [content]}`):
```python
    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    all_tools = core.registry.get_tool_schemas()
    tools = [t for t in all_tools if t["function"]["name"] in defn.tool_names]

    content = ""
    for _ in range(_TOOL_CALL_LIMIT):
        msg = await agents.llm.call_llm(messages, tools=tools or None)
        messages.append(msg)
        if not msg.get("tool_calls"):
            content = msg.get("content") or ""
            break
        for tc in msg["tool_calls"]:
            fn = tc["function"]
            try:
                result = await core.registry.call_tool_async(fn["name"], fn.get("arguments") or {})
            except Exception as exc:
                result = f"[Tool error: {exc}]"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result),
            })
    else:
        content = "[Tool call limit reached]"
    return {"tool_results": [content]}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_custom_agent_tools.py -v --tb=short
```
Expected: 5 passed.

- [ ] **Step 5: Run full suite to check no regressions**

```bash
pytest --tb=short -q
```
Expected: 2 pre-existing failures only (`test_supervisor_does_not_emit_for_respond`, `test_list_sorted_newest_first`).

- [ ] **Step 6: Commit**

```bash
git add agents/custom_agent.py tests/test_custom_agent_tools.py
git commit -m "feat(custom-agent): add tool execution loop"
```

---

### Task 2: Workflow step variables

**Files:**
- Modify: `agents/workflow_store.py`
- Create: `tests/test_workflow_variables.py`

**Interfaces:**
- Produces: `_interpolate(value, results, payload=None, run_vars=None)` — extended signature
- Produces: `_interpolate_params(params, results, payload=None, run_vars=None)` — extended signature
- Produces: `_run_step(step, step_results, payload, run_vars=None)` — `run_vars: dict[str,dict] | None` new optional param
- Produces: `run_workflow` — unchanged external signature; internally tracks `run_vars`

**Current `_interpolate` signature (line 67):**
```python
def _interpolate(value: Any, results: list[str], payload: dict | None = None) -> Any:
```

**Current `_interpolate_params` (line 96):**
```python
def _interpolate_params(params: dict, results: list[str], payload: dict | None = None) -> dict:
    return {k: _interpolate(v, results, payload) for k, v in params.items()}
```

**Current `_run_step` signature (line 103):**
```python
async def _run_step(
    step: dict,
    step_results: list[str],
    payload: dict | None,
) -> tuple[str, str | None]:
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflow_variables.py`:

```python
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
    with patch("core.registry.call_tool_async", call_mock):
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
    with patch("core.registry.call_tool_async", call_mock):
        output = await run_workflow("w")
    assert call_mock.call_args_list[1] == call("t2", {"q": "first"})
    assert output[1]["result"] == "second"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_workflow_variables.py -v --tb=short
```
Expected: `test_interpolate_steps_result` and `test_interpolate_steps_error` fail (`AssertionError` — `{{steps.fetch.result}}` not substituted). The `run_workflow` tests may pass (no `{{steps.name}}` in params, so no substitution needed yet).

- [ ] **Step 3: Extend `_interpolate` and `_interpolate_params`**

In `agents/workflow_store.py`, replace the `_interpolate` function (lines 67–93) with:

```python
def _interpolate(value: Any, results: list[str], payload: dict | None = None, run_vars: dict[str, dict] | None = None) -> Any:
    """Substitute {{prev}}, {{step_N}}, {{payload}}, {{payload.key}}, {{vars.name}}, {{steps.name.result/error}}."""
    if not isinstance(value, str):
        return value
    prev = results[-1] if results else ""
    value = value.replace("{{prev}}", prev)

    def _sub_step(m: re.Match) -> str:
        idx = int(m.group(1))
        return results[idx] if 0 <= idx < len(results) else m.group(0)

    value = re.sub(r"\{\{step_(\d+)\}\}", _sub_step, value)

    if payload is not None:
        value = value.replace("{{payload}}", json.dumps(payload))

        def _sub_payload(m: re.Match) -> str:
            key = m.group(1)
            v = payload.get(key, m.group(0))
            return str(v)

        value = re.sub(r"\{\{payload\.([^}]+)\}\}", _sub_payload, value)

    from agents.variable_store import resolve_vars
    value = resolve_vars(value)

    if run_vars:
        def _sub_steps(m: re.Match) -> str:
            return run_vars.get(m.group(1), {}).get(m.group(2), "")
        value = re.sub(r"\{\{steps\.(\w+)\.(result|error)\}\}", _sub_steps, value)

    return value
```

Replace `_interpolate_params` (lines 96–97) with:

```python
def _interpolate_params(params: dict, results: list[str], payload: dict | None = None, run_vars: dict[str, dict] | None = None) -> dict:
    return {k: _interpolate(v, results, payload, run_vars) for k, v in params.items()}
```

- [ ] **Step 4: Add `run_vars` parameter to `_run_step`**

Replace `_run_step` signature and update all three step branches to pass `run_vars` where they call `_interpolate` or `_interpolate_params`:

```python
async def _run_step(
    step: dict,
    step_results: list[str],
    payload: dict | None,
    run_vars: dict[str, dict] | None = None,
) -> tuple[str, str | None]:
    """Dispatch one workflow step. Returns (result_str, error_str | None)."""
    step_type = step.get("step_type", "tool")

    if step_type == "tool":
        tool = step.get("tool", "")
        params = _interpolate_params(step.get("params", {}), step_results, payload, run_vars)
        result = await call_tool_async(tool, params)
        return str(result), None

    elif step_type == "llm":
        prompt = _interpolate(step.get("prompt", ""), step_results, payload, run_vars)
        system = step.get("system", "")
        msgs = ([{"role": "system", "content": system}] if system else [])
        msgs.append({"role": "user", "content": prompt})
        import agents.llm
        msg = await agents.llm.call_llm(msgs)
        return msg.get("content") or "", None

    elif step_type == "agent":
        from agents.custom_agent import custom_agent_node
        name = step.get("name", "")
        message = _interpolate(step.get("message", "{{prev}}"), step_results, payload, run_vars)
        state = {
            "active_agent": f"custom:{name}",
            "messages": [{"role": "user", "content": message}],
            "memory_context": "",
            "search_provider": "ddg",
            "hop_count": 0,
            "tool_results": [],
            "direct_result": "",
        }
        result = await custom_agent_node(state)
        results_list = result.get("tool_results", [])
        return results_list[0] if results_list else "", None

    else:
        return "", f"Unknown step_type: {step_type!r}"
```

- [ ] **Step 5: Update `run_workflow` to track `run_vars`**

In `run_workflow`, add `run_vars: dict[str, dict] = {}` after `step_results: list[str] = []` (line 157), and update the main loop to pass `run_vars` and store named step results.

Replace the loop body (lines 160–182) with:

```python
        for i, step in enumerate(wf["steps"]):
            note = step.get("note", "")
            step_type = step.get("step_type", "tool")
            t0 = time.monotonic()
            try:
                result_str, error = await _run_step(step, step_results, payload, run_vars)
            except Exception as exc:
                result_str = ""
                error = str(exc)
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
            })
            if error:
                break
```

Also update `dry_run_workflow` to pass `run_vars`. Add `run_vars: dict[str, dict] = {}` after `step_results: list[str] = []` (around line 195), and update all `_interpolate_params` and `_interpolate` calls to pass `run_vars`. Also store named step dry-run results:

```python
        # After appending dry_result to step_results:
        if step_name := step.get("name"):
            run_vars[step_name] = {"result": dry_result, "error": ""}
```

And update `_interpolate_params` and `_interpolate` calls in `dry_run_workflow`:
```python
        params = _interpolate_params(raw_params, step_results, payload, run_vars)
        # for llm:
        prompt = _interpolate(step.get("prompt", ""), step_results, payload, run_vars)
        # for agent:
        message = _interpolate(step.get("message", "{{prev}}"), step_results, payload, run_vars)
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
pytest tests/test_workflow_variables.py tests/test_workflow_store_steps.py -v --tb=short
```
Expected: 4 new tests pass + all existing step tests pass.

- [ ] **Step 7: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_variables.py
git commit -m "feat(workflow): add named step variables ({{steps.name.result}})"
```

---

### Task 3: `if` step type

**Files:**
- Modify: `agents/workflow_store.py`
- Create: `tests/test_workflow_if.py`

**Interfaces:**
- Consumes: `_run_step(step, step_results, payload, run_vars)` from Task 2
- Consumes: `_interpolate_params(params, results, payload, run_vars)` from Task 2
- Produces: `_evaluate_condition(condition: dict, prev: str) -> bool` (new pure function)
- Produces: `_run_step` handles `step_type == "if"` — runs branch steps, returns final branch result

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflow_if.py`:

```python
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
    with patch("core.registry.call_tool_async", AsyncMock(side_effect=["hello world", "yes_result"])):
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
    with patch("core.registry.call_tool_async", AsyncMock(side_effect=["goodbye", "no_result"])):
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
    with patch("core.registry.call_tool_async", AsyncMock(return_value="original")):
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
    with patch("core.registry.call_tool_async", call_mock):
        output = await run_workflow("w")
    assert call_mock.call_args_list[1] == call("t2", {"q": "parent_val"})
    assert output[-1]["result"] == "branch_result"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_workflow_if.py -v --tb=short
```
Expected: `test_evaluate_condition_ops` fails (`ImportError: cannot import name '_evaluate_condition'`); `if` step tests fail with `"Unknown step_type: 'if'"` in output.

- [ ] **Step 3: Add `_evaluate_condition` before `_run_step`**

In `agents/workflow_store.py`, insert this function immediately before `from core.registry import call_tool_async` (line 100):

```python
def _evaluate_condition(condition: dict, prev: str) -> bool:
    """Evaluate a structured condition against prev (the preceding step's result)."""
    op = condition.get("op", "not_empty")
    value = condition.get("value", "")
    actual = prev
    match op:
        case "eq":           return actual == value
        case "ne":           return actual != value
        case "contains":     return value in actual
        case "not_contains": return value not in actual
        case "empty":        return not actual.strip()
        case "not_empty":    return bool(actual.strip())
        case _:              return False
```

- [ ] **Step 4: Add `if` branch to `_run_step`**

In `_run_step`, add the `if` branch after the `agent` branch and before the `else` clause (`return "", f"Unknown step_type: {step_type!r}"`):

```python
    elif step_type == "if":
        prev = step_results[-1] if step_results else ""
        condition = step.get("condition", {})
        branch = step.get("then", []) if _evaluate_condition(condition, prev) else step.get("else", [])
        sub_step_results = list(step_results)  # copy — sub-steps see parent results but don't pollute index
        branch_prev = prev
        for sub_step in branch:
            sub_result, sub_error = await _run_step(sub_step, sub_step_results, payload, run_vars)
            sub_step_results.append(sub_result)
            if sub_error:
                return sub_result, sub_error
            branch_prev = sub_result
        return branch_prev, None
```

- [ ] **Step 5: Add `if` to `dry_run_workflow`**

In `dry_run_workflow`, add an `elif step_type == "if":` branch alongside the existing `llm` and `agent` branches:

```python
        elif step_type == "if":
            condition = step.get("condition", {})
            op = condition.get("op", "not_empty")
            value = condition.get("value", "")
            then_n = len(step.get("then", []))
            else_n = len(step.get("else", []))
            dry_result = f"[DRY RUN] [if] {op} {value!r} → then: {then_n} steps / else: {else_n} steps"
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
pytest tests/test_workflow_if.py tests/test_workflow_store_steps.py tests/test_workflow_variables.py -v --tb=short
```
Expected: all pass.

- [ ] **Step 7: Run full suite**

```bash
pytest --tb=short -q
```
Expected: 2 pre-existing failures only.

- [ ] **Step 8: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_if.py
git commit -m "feat(workflow): add if step type with structured conditions"
```

---

### Task 4: Dashboard UI

**Files:**
- Modify: `dashboard/static/index.html`

**Context:** The workflow step editor was rewritten in Phase 2 (commit `6728791`). Key functions: `wfAddStep(step)`, `_wfStepTypeChanged(idx)`, `_wfCollectSteps()`, `wfLoad(wf)`, `wfNew()`, `wfSave()`. Step cards use CSS classes `.wf-tool-fields`, `.wf-llm-fields`, `.wf-agent-fields` to show/hide field groups on type change. Each step card is rendered by `wfAddStep`.

**What to add:**
1. **Step name input** — on every step card, above the type selector
2. **`if` step type** — new `<option>` in type `<select>`, `.wf-if-fields` group with condition op/value + then/else textareas
3. **Variable picker** — below params textarea on tool/llm/agent steps; shows `{{steps.X.result}}` for named steps defined above

- [ ] **Step 1: Find insertion points**

Search the file for these markers:
```bash
grep -n "wf-step-name\|wf-if-fields\|_wfStepTypeChanged\|wfAddStep\|_wfCollectSteps\|wfLoad\|wfNew\b" dashboard/static/index.html | head -30
```

Note the line numbers for `wfAddStep`, `_wfStepTypeChanged`, `_wfCollectSteps`, `wfLoad`, `wfNew`.

- [ ] **Step 2: Add `wf-step-name` input to each step card in `wfAddStep`**

**Note on `agent` steps:** The existing `agent` step type already uses `step.name` for the agent name (see `_run_step` line `name = step.get("name", "")`). For `agent` steps, the agent selector already populates `name`, so `run_workflow` will automatically track `run_vars[agent_name]` — no extra step-name input is needed. The step-name input added here should only appear for `tool`, `llm`, and `if` step types. For `agent` steps, hide the input (`style="display:none"` when `stepType === 'agent'`).

In the `wfAddStep` function, find where the step HTML is built (look for the step-type `<select>` element). Add a name input above it:

```html
<input class="wf-step-name" placeholder="Step name (optional, for {{steps.name.result}})"
  value="${_esc((step && step.name) || '')}"
  style="width:100%;margin-bottom:.35rem;background:#111;border:1px solid #333;color:#aaa;
         border-radius:3px;padding:3px 6px;font-size:0.75rem;font-family:monospace;">
```

- [ ] **Step 3: Add `if` option to step-type `<select>` in `wfAddStep`**

Find the step-type `<select>` in `wfAddStep`. Add `<option value="if">If (condition)</option>` after the existing options (tool/llm/agent).

Set the correct `selected` attribute: `${stepType === 'if' ? 'selected' : ''}`.

- [ ] **Step 4: Add `.wf-if-fields` group in `wfAddStep`**

After the existing `.wf-tool-fields`, `.wf-llm-fields`, `.wf-agent-fields` divs, add:

```html
<div class="wf-if-fields" style="display:${stepType==='if'?'block':'none'};margin-top:.4rem">
  <div style="display:flex;gap:.4rem;align-items:center;margin-bottom:.35rem">
    <span style="color:#888;font-size:0.75rem">if prev</span>
    <select class="wf-if-op" style="background:#111;border:1px solid #333;color:#ccc;
      font-size:0.75rem;padding:2px 4px;border-radius:3px;">
      <option value="not_empty" ${(step&&step.condition&&step.condition.op)==='not_empty'?'selected':''}>is not empty</option>
      <option value="empty" ${(step&&step.condition&&step.condition.op)==='empty'?'selected':''}>is empty</option>
      <option value="contains" ${(step&&step.condition&&step.condition.op)==='contains'?'selected':''}>contains</option>
      <option value="not_contains" ${(step&&step.condition&&step.condition.op)==='not_contains'?'selected':''}>does not contain</option>
      <option value="eq" ${(step&&step.condition&&step.condition.op)==='eq'?'selected':''}>equals</option>
      <option value="ne" ${(step&&step.condition&&step.condition.op)==='ne'?'selected':''}>does not equal</option>
    </select>
    <input class="wf-if-value" placeholder="value" value="${_esc((step&&step.condition&&step.condition.value)||'')}"
      style="flex:1;background:#111;border:1px solid #333;color:#ccc;border-radius:3px;
             padding:2px 6px;font-size:0.75rem;font-family:monospace;">
  </div>
  <label style="color:#888;font-size:0.75rem">then (JSON step array):</label>
  <textarea class="wf-if-then" rows="3" placeholder='[{"step_type":"tool","tool":"...","params":{}}]'
    style="width:100%;background:#0a0a0a;border:1px solid #333;color:#ccc;border-radius:3px;
           padding:4px 6px;font-size:0.72rem;font-family:monospace;resize:vertical;box-sizing:border-box;margin-top:.2rem"
  >${step && step.then ? JSON.stringify(step.then, null, 2) : ''}</textarea>
  <label style="color:#888;font-size:0.75rem;margin-top:.35rem;display:block">else (JSON step array, optional):</label>
  <textarea class="wf-if-else" rows="3" placeholder='[{"step_type":"llm","prompt":"..."}]'
    style="width:100%;background:#0a0a0a;border:1px solid #333;color:#ccc;border-radius:3px;
           padding:4px 6px;font-size:0.72rem;font-family:monospace;resize:vertical;box-sizing:border-box;margin-top:.2rem"
  >${step && step.else ? JSON.stringify(step.else, null, 2) : ''}</textarea>
</div>
```

- [ ] **Step 5: Update `_wfStepTypeChanged` to handle `if`**

In `_wfStepTypeChanged(idx)`, find where it hides/shows field groups. Add handling for `if`:

```javascript
card.querySelector('.wf-if-fields').style.display = t === 'if' ? 'block' : 'none';
```

(Place alongside the other field-group hide/show lines.)

- [ ] **Step 6: Update `_wfCollectSteps` to serialize `name`, `if` fields**

In `_wfCollectSteps`, find where each step is serialized. Add:

```javascript
// For every step:
const name = card.querySelector('.wf-step-name').value.trim();
if (name) step.name = name;

// For if steps:
if (stepType === 'if') {
  const op = card.querySelector('.wf-if-op').value;
  const val = card.querySelector('.wf-if-value').value.trim();
  step.condition = { op };
  if (val) step.condition.value = val;
  const thenRaw = card.querySelector('.wf-if-then').value.trim();
  const elseRaw = card.querySelector('.wf-if-else').value.trim();
  try { step.then = thenRaw ? JSON.parse(thenRaw) : []; } catch { step.then = []; }
  try { if (elseRaw) step.else = JSON.parse(elseRaw); } catch {}
}
```

- [ ] **Step 7: Add variable picker below params textarea**

In `wfAddStep`, find the `.wf-tool-fields` div's params textarea. Below it, add a picker div:

```html
<div class="wf-var-picker" style="font-size:0.7rem;color:#555;margin-top:.2rem;min-height:1rem"></div>
```

Add a function `_wfUpdateVarPicker()` that scans all step cards for named steps defined above the current card, then updates each `.wf-var-picker` with clickable `{{steps.X.result}}` chips:

```javascript
function _wfUpdateVarPicker() {
  const cards = Array.from(document.querySelectorAll('.wf-step-card'));
  const names = [];
  cards.forEach((card, i) => {
    const n = card.querySelector('.wf-step-name')?.value.trim();
    if (n) names.push({ idx: i, name: n });
    const picker = card.querySelector('.wf-var-picker');
    if (!picker) return;
    const available = names.filter(x => x.idx < i);
    picker.innerHTML = available.length
      ? available.map(x =>
          `<span onclick="navigator.clipboard.writeText('{{steps.${_esc(x.name)}.result}}')"
            style="cursor:pointer;margin-right:.4rem;color:#4af;text-decoration:underline"
            title="Click to copy">{{steps.${_esc(x.name)}.result}}</span>`
        ).join('')
      : '';
  });
}
```

Wire `_wfUpdateVarPicker()` to: step name input `oninput` event, and call it after `wfAddStep`, `wfLoad`, `wfNew`.

- [ ] **Step 8: Verify UI in browser**

Start the server and open the dashboard:
```bash
source .venv/bin/activate
python core/main.py &
# Open http://localhost:8000 → Flows panel
```

Manual checks:
1. Add a step → name input appears above type selector
2. Type a name → variable picker appears on subsequent steps
3. Change step type to "If (condition)" → condition builder + then/else textareas appear; tool/llm/agent fields hide
4. Save a workflow with an `if` step → reload → condition fields repopulate
5. Click a `{{steps.X.result}}` chip → copied to clipboard

Kill the server after verification: `kill %1`

- [ ] **Step 9: Run full suite to confirm no regressions**

```bash
pytest --tb=short -q
```
Expected: 2 pre-existing failures only.

- [ ] **Step 10: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add step name field, if step UI, and variable picker"
```
