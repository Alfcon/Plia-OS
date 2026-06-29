# Agent Builder Phase 2 — Workflow Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend custom agents and workflows with workflow-backed agents, `llm`/`agent` step types, and event-triggered workflow execution.

**Architecture:** Extend in place — `AgentDef` gets `workflow_name`, workflow JSON gets `event_trigger`, `run_workflow` gains `_run_step` dispatcher, a thin `core/event_triggers.py` subscribes to the event bus, API and dashboard UI extended minimally.

**Tech Stack:** FastAPI, LangGraph, Python asyncio, JSON file store, vanilla JS (inline SPA).

## Global Constraints

- No new pip dependencies
- `run_workflow` stays async (already is); no sync wrappers introduced
- Existing tool steps (no `step_type` key) must execute identically after refactor — backward compat required
- Circular import `workflow_store ↔ custom_agent` broken with late imports inside function bodies only
- All tests use `AsyncClient(transport=ASGITransport(app=create_app()))` per project convention (see `tests/test_workflow_store.py` for the exact pattern)
- Mock `call_llm` via `patch("agents.llm.call_llm")`, never patch the module import itself
- Workflow store tests patch `_workflows_path` with `patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json")`
- Agent store tests patch `_AGENTS_FILE` with `patch("core.agent_store._AGENTS_FILE", tmp_path / "agents.json")`
- `reset_events` autouse fixture clears subscribers before/after every test — call `setup_event_triggers()` inside each test that needs it
- `isolate_config_file` autouse fixture redirects config to tmp — `_workflows_path()` derives from `get_config().memory_dir`, so workflow-path isolation for API tests comes from that fixture (no extra patch needed in `AsyncClient` tests)

---

## File Map

| File | Change |
|------|--------|
| `core/agent_store.py` | Add `workflow_name: str \| None = None` to `AgentDef`; update `_from_dict` |
| `agents/workflow_store.py` | Add `event_trigger` to `save_workflow`; extract `_run_step`; update `run_workflow` + `dry_run_workflow` |
| `agents/custom_agent.py` | Add workflow path before existing LLM path |
| `core/event_triggers.py` | **NEW** — event bus subscriber that fires matching workflows |
| `core/main.py` | Call `setup_event_triggers()` eagerly in `create_app()` |
| `dashboard/server.py` | Add `event_trigger` to workflow save; add `workflow_name` to agent create/update |
| `dashboard/static/index.html` | Flows: step_type selector + event_trigger field; Custom Agents: workflow_name select |
| `tests/test_agent_store.py` | Add 2 tests for `workflow_name` roundtrip |
| `tests/test_workflow_store.py` | Add 2 tests for `event_trigger` roundtrip |
| `tests/test_workflow_store_steps.py` | **NEW** — 9 tests for new step types |
| `tests/test_workflow_backed_agent.py` | **NEW** — 5 tests for workflow-backed custom agent |
| `tests/test_event_triggers.py` | **NEW** — 5 tests for event trigger wiring |
| `tests/test_workflow_event_trigger_api.py` | **NEW** — 5 API roundtrip tests |

---

### Task 1: `AgentDef.workflow_name` field

**Files:**
- Modify: `core/agent_store.py`
- Modify: `tests/test_agent_store.py`

**Interfaces:**
- Produces: `AgentDef.workflow_name: str | None` (default `None`); all existing `save_agent` / `get_agent` / `list_agents` callers work unchanged; old JSON without the key loads as `None`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_store.py` (after the existing `test_list_empty` test):

```python
def test_workflow_name_roundtrips(store):
    save_agent(_defn(workflow_name="my-wf"))
    result = get_agent("finance")
    assert result.workflow_name == "my-wf"


def test_workflow_name_defaults_none(store):
    save_agent(_defn())
    result = get_agent("finance")
    assert result.workflow_name is None
```

- [ ] **Step 2: Run tests — expect failures**

```bash
source .venv/bin/activate
pytest tests/test_agent_store.py::test_workflow_name_roundtrips tests/test_agent_store.py::test_workflow_name_defaults_none -v
```

Expected: `TypeError: AgentDef.__init__() got an unexpected keyword argument 'workflow_name'`

- [ ] **Step 3: Add `workflow_name` to `AgentDef` dataclass**

In `core/agent_store.py`, change the dataclass — add after `created_at: str = ""`:

```python
@dataclass
class AgentDef:
    name: str
    display_name: str
    system_prompt: str
    tool_names: list[str]
    keywords: list[str]
    llm_description: str
    enabled: bool = True
    created_at: str = ""
    workflow_name: str | None = None
```

- [ ] **Step 4: Update `_from_dict` to read `workflow_name`**

In `core/agent_store.py`, change `_from_dict`:

```python
def _from_dict(d: dict) -> AgentDef:
    return AgentDef(
        name=d["name"],
        display_name=d.get("display_name", ""),
        system_prompt=d.get("system_prompt", ""),
        tool_names=d.get("tool_names", []),
        keywords=d.get("keywords", []),
        llm_description=d.get("llm_description", ""),
        enabled=bool(d.get("enabled", True)),
        created_at=d.get("created_at", ""),
        workflow_name=d.get("workflow_name", None),
    )
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/test_agent_store.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 6: Run full suite to confirm no regressions**

```bash
pytest --tb=short -q
```

Expected: same pass count as before (560+), 0 new failures.

- [ ] **Step 7: Commit**

```bash
git add core/agent_store.py tests/test_agent_store.py
git commit -m "feat(agent-store): add workflow_name field to AgentDef"
```

---

### Task 2: `event_trigger` on workflow JSON

**Files:**
- Modify: `agents/workflow_store.py`
- Modify: `tests/test_workflow_store.py`

**Interfaces:**
- Consumes: `save_workflow` existing signature `(name, steps, description="")`
- Produces: `save_workflow(name, steps, description="", event_trigger: str | None = None)` — backward compat (new param is optional); `get_workflow` and `list_workflows` return `event_trigger` key in result dict (value may be `None`)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_workflow_store.py` (after existing unit tests, before the API tests section):

```python
def test_save_workflow_with_event_trigger(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        from agents.workflow_store import save_workflow, get_workflow
        save_workflow("trig", [], "desc", event_trigger="reminder_fired")
        wf = get_workflow("trig")
    assert wf["event_trigger"] == "reminder_fired"


def test_event_trigger_defaults_none(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        from agents.workflow_store import save_workflow, get_workflow
        save_workflow("plain", [], "")
        wf = get_workflow("plain")
    assert wf["event_trigger"] is None
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_workflow_store.py::test_save_workflow_with_event_trigger tests/test_workflow_store.py::test_event_trigger_defaults_none -v
```

Expected: FAIL — `event_trigger` key missing from `get_workflow` result.

- [ ] **Step 3: Update `save_workflow` in `agents/workflow_store.py`**

Replace the current `save_workflow` function:

```python
def save_workflow(
    name: str,
    steps: list[dict],
    description: str = "",
    event_trigger: str | None = None,
) -> None:
    data = _load()
    data[name] = {"description": description, "steps": steps, "event_trigger": event_trigger}
    _save(data)
```

- [ ] **Step 4: Run new tests — expect pass**

```bash
pytest tests/test_workflow_store.py -v
```

Expected: all tests PASS (including the 2 new ones and all existing ones).

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_store.py
git commit -m "feat(workflow-store): add event_trigger field to save_workflow"
```

---

### Task 3: Workflow step types (`llm` and `agent`)

**Files:**
- Modify: `agents/workflow_store.py`
- Create: `tests/test_workflow_store_steps.py`

**Interfaces:**
- Consumes: `save_workflow` from Task 2; `call_tool_async` from `core.registry` (already imported at module level)
- Produces: `_run_step(step, step_results, payload) -> tuple[str, str | None]` — private, used only by `run_workflow`; `run_workflow` output dicts now include `"step_type"` key alongside existing keys; `dry_run_workflow` handles `llm`/`agent` steps

- [ ] **Step 1: Create test file with all failing tests**

Create `tests/test_workflow_store_steps.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_workflow_store_steps.py -v
```

Expected: all 9 FAIL — `step_type` key missing, LLM/agent step types unknown.

- [ ] **Step 3: Add `_run_step` to `agents/workflow_store.py`**

Insert the following function after the `_interpolate_params` function (before `from core.registry import call_tool_async`):

```python
async def _run_step(
    step: dict,
    step_results: list[str],
    payload: dict | None,
) -> tuple[str, str | None]:
    """Dispatch one workflow step. Returns (result_str, error_str | None)."""
    step_type = step.get("step_type", "tool")

    if step_type == "tool":
        tool = step.get("tool", "")
        params = _interpolate_params(step.get("params", {}), step_results, payload)
        result = await call_tool_async(tool, params)
        return str(result), None

    elif step_type == "llm":
        prompt = _interpolate(step.get("prompt", ""), step_results, payload)
        system = step.get("system", "")
        msgs = ([{"role": "system", "content": system}] if system else [])
        msgs.append({"role": "user", "content": prompt})
        import agents.llm
        msg = await agents.llm.call_llm(msgs)
        return msg.get("content") or "", None

    elif step_type == "agent":
        from agents.custom_agent import custom_agent_node
        name = step.get("name", "")
        message = _interpolate(step.get("message", "{{prev}}"), step_results, payload)
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

**Note:** `_run_step` must be placed AFTER `from core.registry import call_tool_async` at line 92 of the current file, since it calls `call_tool_async`. Move the import line above the function if needed, or place `_run_step` after line 92.

- [ ] **Step 4: Replace `run_workflow` loop with `_run_step` dispatch**

Replace the entire `run_workflow` function:

```python
async def run_workflow(name: str, payload: dict | None = None) -> list[dict]:
    wf = get_workflow(name)
    if wf is None:
        raise KeyError(f"Workflow {name!r} not found")

    step_results: list[str] = []
    output: list[dict] = []

    for i, step in enumerate(wf["steps"]):
        note = step.get("note", "")
        step_type = step.get("step_type", "tool")
        t0 = time.monotonic()
        try:
            result_str, error = await _run_step(step, step_results, payload)
        except Exception as exc:
            result_str = ""
            error = str(exc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        step_results.append(result_str)
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

    return output
```

- [ ] **Step 5: Replace `dry_run_workflow` with step-type-aware version**

Replace the entire `dry_run_workflow` function:

```python
async def dry_run_workflow(name: str, payload: dict | None = None) -> list[dict]:
    """Simulate a workflow run without executing tool calls."""
    wf = get_workflow(name)
    if wf is None:
        raise KeyError(f"Workflow {name!r} not found")

    step_results: list[str] = []
    output: list[dict] = []

    for i, step in enumerate(wf["steps"]):
        step_type = step.get("step_type", "tool")
        tool = step.get("tool", "")
        raw_params = step.get("params", {})
        note = step.get("note", "")
        params = _interpolate_params(raw_params, step_results, payload)

        if step_type == "llm":
            prompt = _interpolate(step.get("prompt", ""), step_results, payload)
            dry_result = f"[DRY RUN] would call LLM with prompt: {prompt!r}"
        elif step_type == "agent":
            agent_name = step.get("name", "")
            message = _interpolate(step.get("message", "{{prev}}"), step_results, payload)
            dry_result = f"[DRY RUN] would call agent {agent_name!r} with: {message!r}"
        else:
            dry_result = f"[DRY RUN] would call {tool!r} with {params}"

        step_results.append(dry_result)
        output.append({
            "step": i,
            "step_type": step_type,
            "tool": tool,
            "params": params,
            "note": note,
            "result": dry_result,
            "error": None,
            "duration_ms": 0,
            "dry_run": True,
        })

    return output
```

- [ ] **Step 6: Run new tests — expect pass**

```bash
pytest tests/test_workflow_store_steps.py -v
```

Expected: all 9 PASS.

- [ ] **Step 7: Run full suite**

```bash
pytest --tb=short -q
```

Expected: no regressions (existing `test_workflow_store.py`, `test_workflow_dryrun.py` still pass).

- [ ] **Step 8: Commit**

```bash
git add agents/workflow_store.py tests/test_workflow_store_steps.py
git commit -m "feat(workflow-store): add llm and agent step types"
```

---

### Task 4: Workflow-backed custom agent

**Files:**
- Modify: `agents/custom_agent.py`
- Create: `tests/test_workflow_backed_agent.py`

**Interfaces:**
- Consumes: `AgentDef.workflow_name` from Task 1; `run_workflow` from Task 3
- Produces: `custom_agent_node` — when `defn.workflow_name` is set, calls `run_workflow(defn.workflow_name, payload={"message": user_msg})` and returns last step result; `KeyError` from missing workflow → friendly error string; workflow step error → surfaced in `tool_results`

- [ ] **Step 1: Create test file**

Create `tests/test_workflow_backed_agent.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_workflow_backed_agent.py -v
```

Expected: `test_workflow_name_routes_to_run_workflow` FAIL (no workflow path in node), others may vary.

- [ ] **Step 3: Add workflow path to `agents/custom_agent.py`**

Replace the entire `custom_agent_node` function:

```python
async def custom_agent_node(state: "AgentState") -> dict:
    name = state["active_agent"].removeprefix("custom:")
    defn = await asyncio.to_thread(get_agent, name)
    if not defn or not defn.enabled:
        return {"tool_results": [f"Custom agent '{name}' not found or disabled"]}

    if defn.workflow_name:
        from agents.workflow_store import run_workflow
        user_msg = next(
            (m["content"] for m in state["messages"] if m["role"] == "user"), ""
        )
        try:
            output = await run_workflow(defn.workflow_name, payload={"message": user_msg})
        except KeyError:
            return {"tool_results": [f"Workflow '{defn.workflow_name}' not found"]}
        if output and output[-1].get("error"):
            return {"tool_results": [f"Workflow error: {output[-1]['error']}"]}
        return {"tool_results": [output[-1]["result"] if output else ""]}

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

- [ ] **Step 4: Run new tests — expect pass**

```bash
pytest tests/test_workflow_backed_agent.py -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

Expected: no regressions (existing `tests/test_custom_agent_node.py` still passes).

- [ ] **Step 6: Commit**

```bash
git add agents/custom_agent.py tests/test_workflow_backed_agent.py
git commit -m "feat(custom-agent): delegate to workflow when workflow_name is set"
```

---

### Task 5: Event triggers

**Files:**
- Create: `core/event_triggers.py`
- Modify: `core/main.py`
- Create: `tests/test_event_triggers.py`

**Interfaces:**
- Consumes: `core.events.subscribe` / `emit`; `agents.workflow_store.list_workflows` / `run_workflow`; `event_trigger` field from Task 2
- Produces: `setup_event_triggers() -> None` — subscribes `_on_event` to event bus; called eagerly in `create_app()`; subscriber receives `{"type": event_type, **data}` (event bus merges type into payload dict)

- [ ] **Step 1: Create test file**

Create `tests/test_event_triggers.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from core import events


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


def test_setup_subscribes():
    from core.event_triggers import setup_event_triggers, _on_event
    setup_event_triggers()
    assert events.is_subscribed(_on_event)


@pytest.mark.asyncio
async def test_matching_event_fires_workflow(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("brief", [], "d", event_trigger="reminder_fired")
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        setup_event_triggers()
        await events.emit("reminder_fired", {"msg": "time"})
    mock_run.assert_called_once_with(
        "brief",
        payload={"type": "reminder_fired", "msg": "time"},
    )


@pytest.mark.asyncio
async def test_non_matching_event_ignored(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("brief", [], "d", event_trigger="reminder_fired")
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        setup_event_triggers()
        await events.emit("status", {"state": "armed"})
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_exception_does_not_propagate(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("bad", [], "d", event_trigger="reminder_fired")
    with patch("agents.workflow_store.run_workflow", AsyncMock(side_effect=RuntimeError("boom"))):
        setup_event_triggers()
        await events.emit("reminder_fired", {})  # must not raise


@pytest.mark.asyncio
async def test_workflow_without_trigger_not_fired(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("plain", [], "d")  # no event_trigger
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        setup_event_triggers()
        await events.emit("reminder_fired", {})
    mock_run.assert_not_called()
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_event_triggers.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.event_triggers'`

- [ ] **Step 3: Create `core/event_triggers.py`**

Create new file `core/event_triggers.py`:

```python
from __future__ import annotations
import logging
from core import events

logger = logging.getLogger(__name__)


async def _on_event(payload: dict) -> None:
    from agents.workflow_store import list_workflows, run_workflow
    event_type = payload.get("type")
    for wf in list_workflows():
        if wf.get("event_trigger") == event_type:
            try:
                await run_workflow(wf["name"], payload=payload)
            except Exception:
                logger.exception(
                    "Event trigger failed (workflow=%s, event=%s)",
                    wf["name"],
                    event_type,
                )


def setup_event_triggers() -> None:
    events.subscribe(_on_event)
```

- [ ] **Step 4: Run new tests — expect pass**

```bash
pytest tests/test_event_triggers.py -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Wire `setup_event_triggers()` into `core/main.py`**

In `core/main.py`, add the import and call inside `create_app()` right after `setup_event_forwarding()`:

Current code (around line 61-63):
```python
    load_modules()
    setup_event_forwarding()
    from core.notifier import setup_notifier
```

Change to:
```python
    load_modules()
    setup_event_forwarding()
    from core.event_triggers import setup_event_triggers
    setup_event_triggers()
    from core.notifier import setup_notifier
```

- [ ] **Step 6: Run full suite**

```bash
pytest --tb=short -q
```

Expected: no regressions. The `reset_events` autouse fixture clears subscribers between tests, so `setup_event_triggers()` called inside `create_app()` during API tests doesn't bleed into unit tests.

- [ ] **Step 7: Commit**

```bash
git add core/event_triggers.py core/main.py tests/test_event_triggers.py
git commit -m "feat(event-triggers): fire workflows on matching Plia events"
```

---

### Task 6: API changes

**Files:**
- Modify: `dashboard/server.py`
- Create: `tests/test_workflow_event_trigger_api.py`

**Interfaces:**
- Consumes: `save_workflow(..., event_trigger=...)` from Task 2; `AgentDef.workflow_name` from Task 1
- Produces: `POST /api/workflows` accepts optional `event_trigger` string; `GET /api/workflows` returns it; `POST /api/agents` + `PUT /api/agents/{name}` accept optional `workflow_name` string; `GET /api/agents/{name}` returns it

- [ ] **Step 1: Create test file**

Create `tests/test_workflow_event_trigger_api.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


@pytest.fixture()
def agent_path(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "agents.json"):
        yield


@pytest.mark.asyncio
async def test_workflow_event_trigger_saved(wf_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/workflows", json={
            "name": "trig-wf", "steps": [], "description": "d",
            "event_trigger": "reminder_fired",
        })
        assert r.status_code == 200
        r2 = await c.get("/api/workflows")
    match = next(w for w in r2.json()["workflows"] if w["name"] == "trig-wf")
    assert match["event_trigger"] == "reminder_fired"


@pytest.mark.asyncio
async def test_workflow_event_trigger_defaults_none(wf_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/workflows", json={"name": "plain", "steps": [], "description": ""})
        r2 = await c.get("/api/workflows")
    match = next(w for w in r2.json()["workflows"] if w["name"] == "plain")
    assert match["event_trigger"] is None


@pytest.mark.asyncio
async def test_agent_workflow_name_create(agent_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json={
            "name": "briefer",
            "display_name": "Briefer",
            "system_prompt": "You summarize.",
            "tool_names": [],
            "keywords": [],
            "llm_description": "",
            "workflow_name": "daily-brief",
        })
    assert r.status_code == 201
    assert r.json()["workflow_name"] == "daily-brief"


@pytest.mark.asyncio
async def test_agent_workflow_name_update(agent_path):
    base = {
        "name": "briefer", "display_name": "Briefer",
        "system_prompt": "You summarize.", "tool_names": [],
        "keywords": [], "llm_description": "",
    }
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=base)
        r = await c.put("/api/agents/briefer", json={**base, "workflow_name": "new-wf"})
    assert r.status_code == 200
    assert r.json()["workflow_name"] == "new-wf"


@pytest.mark.asyncio
async def test_agent_workflow_name_defaults_none(agent_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json={
            "name": "plain", "display_name": "Plain",
            "system_prompt": "...", "tool_names": [], "keywords": [], "llm_description": "",
        })
    assert r.json()["workflow_name"] is None
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_workflow_event_trigger_api.py -v
```

Expected: `event_trigger` and `workflow_name` keys missing from responses.

- [ ] **Step 3: Add `event_trigger` to `POST /api/workflows` in `dashboard/server.py`**

Current code at lines 2767-2778:
```python
@router.post("/api/workflows")
async def save_workflow_endpoint(body: dict):
    from agents.workflow_store import save_workflow
    name = body.get("name", "").strip()
    steps = body.get("steps", [])
    description = body.get("description", "")
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="steps must be a list")
    await asyncio.to_thread(save_workflow, name, steps, description)
    return {"ok": True, "name": name}
```

Replace with:
```python
@router.post("/api/workflows")
async def save_workflow_endpoint(body: dict):
    from agents.workflow_store import save_workflow
    name = body.get("name", "").strip()
    steps = body.get("steps", [])
    description = body.get("description", "")
    event_trigger = (body.get("event_trigger") or "").strip() or None
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="steps must be a list")
    await asyncio.to_thread(save_workflow, name, steps, description, event_trigger=event_trigger)
    return {"ok": True, "name": name}
```

- [ ] **Step 4: Add `workflow_name` to `POST /api/agents` in `dashboard/server.py`**

Current code at lines 4940-4948 (inside `create_custom_agent`):
```python
        defn = AgentDef(
            name=name,
            display_name=(body.get("display_name") or "").strip(),
            system_prompt=(body.get("system_prompt") or "").strip(),
            tool_names=list(body.get("tool_names") or []),
            keywords=list(body.get("keywords") or []),
            llm_description=(body.get("llm_description") or "").strip(),
            enabled=bool(body.get("enabled", True)),
        )
```

Replace with:
```python
        defn = AgentDef(
            name=name,
            display_name=(body.get("display_name") or "").strip(),
            system_prompt=(body.get("system_prompt") or "").strip(),
            tool_names=list(body.get("tool_names") or []),
            keywords=list(body.get("keywords") or []),
            llm_description=(body.get("llm_description") or "").strip(),
            enabled=bool(body.get("enabled", True)),
            workflow_name=(body.get("workflow_name") or "").strip() or None,
        )
```

- [ ] **Step 5: Add `workflow_name` to `PUT /api/agents/{name}` in `dashboard/server.py`**

Current code at lines 4973-4982 (inside `update_custom_agent`):
```python
    updated = AgentDef(
        name=name,
        display_name=(body.get("display_name") or "").strip(),
        system_prompt=(body.get("system_prompt") or "").strip(),
        tool_names=list(body.get("tool_names") or []),
        keywords=list(body.get("keywords") or []),
        llm_description=(body.get("llm_description") or "").strip(),
        enabled=bool(body.get("enabled", True)),
        created_at=existing.created_at,
    )
```

Replace with:
```python
    updated = AgentDef(
        name=name,
        display_name=(body.get("display_name") or "").strip(),
        system_prompt=(body.get("system_prompt") or "").strip(),
        tool_names=list(body.get("tool_names") or []),
        keywords=list(body.get("keywords") or []),
        llm_description=(body.get("llm_description") or "").strip(),
        enabled=bool(body.get("enabled", True)),
        created_at=existing.created_at,
        workflow_name=(body.get("workflow_name") or "").strip() or None,
    )
```

- [ ] **Step 6: Run new tests — expect pass**

```bash
pytest tests/test_workflow_event_trigger_api.py -v
```

Expected: all 5 PASS.

- [ ] **Step 7: Run full suite**

```bash
pytest --tb=short -q
```

Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add dashboard/server.py tests/test_workflow_event_trigger_api.py
git commit -m "feat(api): add event_trigger and workflow_name to workflow and agent endpoints"
```

---

### Task 7: Dashboard UI

**Files:**
- Modify: `dashboard/static/index.html`

No automated tests — verify by running the server and using the UI.

**Summary of changes:**
1. Flows panel HTML: add `wf-trigger` input below name/desc row
2. Flows JS `wfNew()`: clear `wf-trigger`
3. Flows JS `wfLoad()`: populate `wf-trigger` from `wf.event_trigger`
4. Flows JS `wfSave()`: include `event_trigger` in POST body
5. Flows JS `wfAddStep()`: add `step_type` select + conditional field groups
6. New Flows JS `_wfStepTypeChanged()`: show/hide field groups on select change
7. Flows JS `_wfCollectSteps()`: read from correct field group based on `step_type`
8. Flows JS `wfRunNamed()`: display `step_type` in results header when `tool` is empty
9. Custom Agents HTML: add `ca-workflow-name` select to form
10. Custom Agents JS `caShowForm()`: populate `ca-workflow-name` from `GET /api/workflows`
11. Custom Agents JS `caSave()`: include `workflow_name` in body

- [ ] **Step 1: Add `wf-trigger` input to Flows panel HTML**

Find lines 3067-3069 in `index.html` (the `wf-name` / `wf-desc` row). After that `<div>`, add a new row div inside the right-column flex container before `<!-- Steps -->`:

Current HTML (around line 3066-3074):
```html
              <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;flex-wrap:wrap;">
                <input id="wf-name" placeholder="Workflow name" style="flex:1;min-width:80px;background:#111;border:1px solid #333;color:#e0e0e0;border-radius:3px;padding:3px 7px;font-size:0.75rem;font-family:monospace;">
                <input id="wf-desc" placeholder="Description (optional)" style="flex:2;min-width:100px;background:#111;border:1px solid #333;color:#888;border-radius:3px;padding:3px 7px;font-size:0.72rem;">
                <button onclick="wfSave()" style="background:#0d2a1a;border:1px solid #1b5e20;color:#81c784;font-size:0.7rem;padding:3px 9px;border-radius:3px;cursor:pointer;">Save</button>
                <button onclick="wfRun()" id="wf-run-btn" style="background:#0d1b2a;border:1px solid #1b3a5e;color:#4fc3f7;font-size:0.7rem;padding:3px 9px;border-radius:3px;cursor:pointer;">▶ Run</button>
              </div>
              <!-- Steps -->
```

Replace with:
```html
              <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;flex-wrap:wrap;">
                <input id="wf-name" placeholder="Workflow name" style="flex:1;min-width:80px;background:#111;border:1px solid #333;color:#e0e0e0;border-radius:3px;padding:3px 7px;font-size:0.75rem;font-family:monospace;">
                <input id="wf-desc" placeholder="Description (optional)" style="flex:2;min-width:100px;background:#111;border:1px solid #333;color:#888;border-radius:3px;padding:3px 7px;font-size:0.72rem;">
                <button onclick="wfSave()" style="background:#0d2a1a;border:1px solid #1b5e20;color:#81c784;font-size:0.7rem;padding:3px 9px;border-radius:3px;cursor:pointer;">Save</button>
                <button onclick="wfRun()" id="wf-run-btn" style="background:#0d1b2a;border:1px solid #1b3a5e;color:#4fc3f7;font-size:0.7rem;padding:3px 9px;border-radius:3px;cursor:pointer;">▶ Run</button>
              </div>
              <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;">
                <span style="color:#333;font-size:0.65rem;flex-shrink:0;white-space:nowrap;">Event trigger</span>
                <input id="wf-trigger" placeholder="reminder_fired (blank = none)" title="Plia event type that auto-fires this workflow"
                  style="flex:1;background:#111;border:1px solid #333;color:#888;border-radius:3px;padding:3px 7px;font-size:0.72rem;">
              </div>
              <!-- Steps -->
```

- [ ] **Step 2: Add `ca-workflow-name` select to Custom Agents form HTML**

Find the Custom Agents form (around line 2812-2815):
```html
            <div id="ca-tools-list" style="max-height:200px;overflow-y:auto;background:#111;border:1px solid #333;border-radius:4px;padding:.5rem;margin-bottom:.75rem">Loading tools…</div>
            <label style="display:flex;align-items:center;gap:.5rem;margin-bottom:1rem">
              <input type="checkbox" id="ca-enabled" checked /> Enabled
            </label>
```

Replace with:
```html
            <div id="ca-tools-list" style="max-height:200px;overflow-y:auto;background:#111;border:1px solid #333;border-radius:4px;padding:.5rem;margin-bottom:.75rem">Loading tools…</div>
            <label>Workflow Name <small style="color:#555">(optional — overrides LLM at runtime if set)</small></label>
            <select id="ca-workflow-name" style="width:100%;margin-bottom:.75rem;background:#111;border:1px solid #333;color:#e0e0e0;border-radius:4px;padding:4px 7px;font-size:0.85rem;">
              <option value="">None (LLM-backed)</option>
            </select>
            <label style="display:flex;align-items:center;gap:.5rem;margin-bottom:1rem">
              <input type="checkbox" id="ca-enabled" checked /> Enabled
            </label>
```

- [ ] **Step 3: Update `wfNew()` JS function**

Find `wfNew()` (around line 10712):
```javascript
  function wfNew() {
    document.getElementById('wf-name').value = '';
    document.getElementById('wf-desc').value = '';
    document.getElementById('wf-steps').innerHTML = '';
    document.getElementById('wf-results').style.display = 'none';
    document.getElementById('wf-results').innerHTML = '';
  }
```

Replace with:
```javascript
  function wfNew() {
    document.getElementById('wf-name').value = '';
    document.getElementById('wf-desc').value = '';
    document.getElementById('wf-trigger').value = '';
    document.getElementById('wf-steps').innerHTML = '';
    document.getElementById('wf-results').style.display = 'none';
    document.getElementById('wf-results').innerHTML = '';
  }
```

- [ ] **Step 4: Update `wfLoad()` JS function**

Find `wfLoad(name)` (around line 10720):
```javascript
  function wfLoad(name) {
    fetch('/api/workflows').then(r => r.json()).then(data => {
      const wf = data.workflows.find(w => w.name === name);
      if (!wf) return;
      document.getElementById('wf-name').value = wf.name;
      document.getElementById('wf-desc').value = wf.description || '';
      document.getElementById('wf-steps').innerHTML = '';
      document.getElementById('wf-results').style.display = 'none';
      (wf.steps || []).forEach(step => wfAddStep(step));
    }).catch(() => {});
  }
```

Replace with:
```javascript
  function wfLoad(name) {
    fetch('/api/workflows').then(r => r.json()).then(data => {
      const wf = data.workflows.find(w => w.name === name);
      if (!wf) return;
      document.getElementById('wf-name').value = wf.name;
      document.getElementById('wf-desc').value = wf.description || '';
      document.getElementById('wf-trigger').value = wf.event_trigger || '';
      document.getElementById('wf-steps').innerHTML = '';
      document.getElementById('wf-results').style.display = 'none';
      (wf.steps || []).forEach(step => wfAddStep(step));
    }).catch(() => {});
  }
```

- [ ] **Step 5: Update `wfSave()` to include `event_trigger`**

Find `wfSave()` (around line 10794):
```javascript
  async function wfSave() {
    const name = document.getElementById('wf-name').value.trim();
    const description = document.getElementById('wf-desc').value.trim();
    if (!name) { alert('Workflow name required'); return; }
    const steps = _wfCollectSteps();
    try {
      const r = await fetch('/api/workflows', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name, description, steps}),
      });
      if (!r.ok) { const e = await r.json(); alert(e.detail || 'Save failed'); return; }
      loadWorkflows();
    } catch(e) { alert('Network error'); }
  }
```

Replace with:
```javascript
  async function wfSave() {
    const name = document.getElementById('wf-name').value.trim();
    const description = document.getElementById('wf-desc').value.trim();
    const event_trigger = document.getElementById('wf-trigger').value.trim() || null;
    if (!name) { alert('Workflow name required'); return; }
    const steps = _wfCollectSteps();
    try {
      const r = await fetch('/api/workflows', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name, description, steps, event_trigger}),
      });
      if (!r.ok) { const e = await r.json(); alert(e.detail || 'Save failed'); return; }
      loadWorkflows();
    } catch(e) { alert('Network error'); }
  }
```

- [ ] **Step 6: Replace `wfAddStep()` with step-type-aware version**

Find `wfAddStep(step)` (around line 10740). Replace the entire function:

```javascript
  function wfAddStep(step) {
    const idx = _wfStepIdx++;
    const stepType = (step && step.step_type) || 'tool';
    const tool = (step && step.tool) || '';
    const params = (step && step.params) ? JSON.stringify(step.params, null, 2) : '{}';
    const note = (step && step.note) || '';
    const prompt = (step && step.prompt) || '';
    const system = (step && step.system) || '';
    const agentName = (step && step.name) || '';
    const message = (step && step.message) || '{{prev}}';
    const container = document.getElementById('wf-steps');
    const div = document.createElement('div');
    div.dataset.stepIdx = idx;
    div.style.cssText = 'border:1px solid #1a1a1a;border-radius:3px;padding:5px 7px;background:#0a0a0a;display:flex;flex-direction:column;gap:4px;';
    div.innerHTML = `
      <div style="display:flex;align-items:center;gap:5px;">
        <select class="wf-step-type" onchange="_wfStepTypeChanged(this)"
          style="background:#111;border:1px solid #333;color:#ccc;font-size:0.7rem;padding:2px 4px;border-radius:3px;">
          <option value="tool" ${stepType==='tool'?'selected':''}>Tool</option>
          <option value="llm" ${stepType==='llm'?'selected':''}>LLM</option>
          <option value="agent" ${stepType==='agent'?'selected':''}>Agent</option>
        </select>
        <button onclick="this.closest('[data-step-idx]').remove()" style="background:none;border:none;color:#555;font-size:0.8rem;cursor:pointer;padding:0 3px;margin-left:auto;">✕</button>
        <button onclick="_wfMoveStep(this,-1)" style="background:none;border:none;color:#555;font-size:0.7rem;cursor:pointer;padding:0 2px;">↑</button>
        <button onclick="_wfMoveStep(this,1)" style="background:none;border:none;color:#555;font-size:0.7rem;cursor:pointer;padding:0 2px;">↓</button>
      </div>
      <div class="wf-tool-fields" style="display:${stepType==='tool'?'flex':'none'};flex-direction:column;gap:4px;">
        <div style="display:flex;align-items:center;gap:5px;">
          <span style="color:#333;font-size:0.65rem;flex-shrink:0;">Tool</span>
          <select class="wf-tool-sel" style="background:#111;border:1px solid #333;color:#ccc;font-size:0.7rem;padding:2px 4px;border-radius:3px;font-family:monospace;flex:1;min-width:0;">
            ${_wfToolNames.map(t => `<option value="${_esc(t)}" ${t === tool ? 'selected' : ''}>${_esc(t)}</option>`).join('')}
          </select>
        </div>
        <div style="display:flex;align-items:flex-start;gap:5px;">
          <span style="color:#333;font-size:0.65rem;flex-shrink:0;padding-top:3px;">Params</span>
          <textarea class="wf-params" rows="3"
            style="flex:1;background:#060606;border:1px solid #222;color:#aaa;font-size:0.68rem;font-family:monospace;padding:3px 5px;border-radius:2px;resize:vertical;min-height:44px;"
            placeholder='{"key": "{{prev}}"}'>${_esc(params)}</textarea>
        </div>
      </div>
      <div class="wf-llm-fields" style="display:${stepType==='llm'?'flex':'none'};flex-direction:column;gap:4px;">
        <div style="display:flex;align-items:flex-start;gap:5px;">
          <span style="color:#333;font-size:0.65rem;flex-shrink:0;padding-top:3px;">Prompt</span>
          <textarea class="wf-prompt" rows="3"
            style="flex:1;background:#060606;border:1px solid #222;color:#aaa;font-size:0.68rem;font-family:monospace;padding:3px 5px;border-radius:2px;resize:vertical;min-height:44px;"
            placeholder="Summarize: {{prev}}">${_esc(prompt)}</textarea>
        </div>
        <div style="display:flex;align-items:center;gap:5px;">
          <span style="color:#333;font-size:0.65rem;flex-shrink:0;">System</span>
          <input type="text" class="wf-system" value="${_esc(system)}" placeholder="optional system prompt"
            style="flex:1;background:#111;border:1px solid #1a1a1a;color:#888;font-size:0.68rem;padding:2px 5px;border-radius:2px;">
        </div>
      </div>
      <div class="wf-agent-fields" style="display:${stepType==='agent'?'flex':'none'};flex-direction:column;gap:4px;">
        <div style="display:flex;align-items:center;gap:5px;">
          <span style="color:#333;font-size:0.65rem;flex-shrink:0;">Agent</span>
          <input type="text" class="wf-agent-name" value="${_esc(agentName)}" placeholder="agent-slug"
            style="flex:1;background:#111;border:1px solid #333;color:#ccc;font-size:0.68rem;padding:2px 5px;border-radius:2px;font-family:monospace;">
        </div>
        <div style="display:flex;align-items:center;gap:5px;">
          <span style="color:#333;font-size:0.65rem;flex-shrink:0;">Msg</span>
          <input type="text" class="wf-agent-msg" value="${_esc(message)}" placeholder="{{prev}}"
            style="flex:1;background:#111;border:1px solid #1a1a1a;color:#888;font-size:0.68rem;padding:2px 5px;border-radius:2px;">
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:5px;">
        <span style="color:#333;font-size:0.65rem;flex-shrink:0;">Note</span>
        <input type="text" class="wf-note" value="${_esc(note)}" placeholder="optional step label"
          style="flex:1;background:#111;border:1px solid #1a1a1a;color:#555;font-size:0.68rem;padding:2px 5px;border-radius:2px;">
      </div>`;
    container.appendChild(div);
  }
```

- [ ] **Step 7: Add `_wfStepTypeChanged()` helper**

Insert after `wfAddStep` (after line 10771, before `_wfMoveStep`):

```javascript
  function _wfStepTypeChanged(sel) {
    const div = sel.closest('[data-step-idx]');
    div.querySelector('.wf-tool-fields').style.display = sel.value === 'tool' ? 'flex' : 'none';
    div.querySelector('.wf-llm-fields').style.display = sel.value === 'llm' ? 'flex' : 'none';
    div.querySelector('.wf-agent-fields').style.display = sel.value === 'agent' ? 'flex' : 'none';
  }
```

- [ ] **Step 8: Replace `_wfCollectSteps()` with step-type-aware version**

Find `_wfCollectSteps()` (around line 10784):
```javascript
  function _wfCollectSteps() {
    return Array.from(document.querySelectorAll('#wf-steps > [data-step-idx]')).map(div => {
      const tool = div.querySelector('.wf-tool-sel').value;
      let params = {};
      try { params = JSON.parse(div.querySelector('.wf-params').value || '{}'); } catch(e) {}
      const note = div.querySelector('.wf-note').value;
      return {tool, params, note};
    });
  }
```

Replace with:
```javascript
  function _wfCollectSteps() {
    return Array.from(document.querySelectorAll('#wf-steps > [data-step-idx]')).map(div => {
      const stepType = div.querySelector('.wf-step-type').value;
      const note = div.querySelector('.wf-note').value;
      if (stepType === 'llm') {
        return {
          step_type: 'llm',
          prompt: div.querySelector('.wf-prompt').value,
          system: div.querySelector('.wf-system').value,
          note,
        };
      } else if (stepType === 'agent') {
        return {
          step_type: 'agent',
          name: div.querySelector('.wf-agent-name').value,
          message: div.querySelector('.wf-agent-msg').value,
          note,
        };
      } else {
        const tool = div.querySelector('.wf-tool-sel').value;
        let params = {};
        try { params = JSON.parse(div.querySelector('.wf-params').value || '{}'); } catch(e) {}
        return {tool, params, note};
      }
    });
  }
```

- [ ] **Step 9: Update `wfRunNamed()` to display step_type when tool is empty**

Find in `wfRunNamed` (around line 10826):
```javascript
        const hdr = `<span style="color:${ok?'#81c784':'#ef5350'};font-size:0.65rem;font-weight:600;">[${i}] ${_esc(s.tool)}</span>
```

Replace with:
```javascript
        const hdr = `<span style="color:${ok?'#81c784':'#ef5350'};font-size:0.65rem;font-weight:600;">[${i}] ${_esc(s.tool || s.step_type || '')}</span>
```

- [ ] **Step 10: Update `caShowForm()` to populate `ca-workflow-name`**

Find in `caShowForm` the line `document.getElementById('ca-form-wrap').style.display = 'block';` (around line 10597). Insert before it:

```javascript
    const wfSel = document.getElementById('ca-workflow-name');
    try {
      const wr = await fetch('/api/workflows');
      if (wr.ok) {
        const wd = await wr.json();
        const currentWf = defn.workflow_name || '';
        wfSel.innerHTML = '<option value="">None (LLM-backed)</option>'
          + (wd.workflows || []).map(w =>
              `<option value="${_esc(w.name)}" ${w.name === currentWf ? 'selected' : ''}>${_esc(w.name)}</option>`
            ).join('');
      }
    } catch(e) {}
```

- [ ] **Step 11: Update `caSave()` to include `workflow_name`**

Find `caSave()` body (around line 10607). In the `body` object, add `workflow_name`:

Current code:
```javascript
    const body = {
      name,
      display_name: document.getElementById('ca-display-name').value.trim(),
      system_prompt: document.getElementById('ca-system-prompt').value.trim(),
      keywords: document.getElementById('ca-keywords').value.split(',').map(s=>s.trim()).filter(Boolean),
      llm_description: document.getElementById('ca-llm-desc').value.trim(),
      tool_names: [...document.querySelectorAll('#ca-tools-list input:checked')].map(el=>el.value),
      enabled: document.getElementById('ca-enabled').checked,
    };
```

Replace with:
```javascript
    const body = {
      name,
      display_name: document.getElementById('ca-display-name').value.trim(),
      system_prompt: document.getElementById('ca-system-prompt').value.trim(),
      keywords: document.getElementById('ca-keywords').value.split(',').map(s=>s.trim()).filter(Boolean),
      llm_description: document.getElementById('ca-llm-desc').value.trim(),
      tool_names: [...document.querySelectorAll('#ca-tools-list input:checked')].map(el=>el.value),
      enabled: document.getElementById('ca-enabled').checked,
      workflow_name: document.getElementById('ca-workflow-name').value || null,
    };
```

- [ ] **Step 12: Manual verification**

Start the server:
```bash
source .venv/bin/activate
python core/main.py
```

Open http://localhost:8000 and verify:
1. Flows panel → click "+ Add Step" → step_type select shows Tool/LLM/Agent options
2. Change to LLM → tool fields hide, Prompt + System fields appear
3. Change to Agent → agent fields appear (Agent slug + Msg)
4. Change back to Tool → tool fields return
5. Enter a workflow name and set event_trigger → Save → reload page → event_trigger still shown
6. Custom Agents panel → "New Agent" → Workflow Name select shows "None (LLM-backed)" + any existing workflows
7. Select a workflow → Save → reload → workflow_name still selected

- [ ] **Step 13: Run full test suite**

```bash
pytest --tb=short -q
```

Expected: all tests pass (no regressions from JS-only changes).

- [ ] **Step 14: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add step_type selector, event_trigger, and workflow_name to UI"
```

---

## Self-Review

**Spec coverage:**
- ✅ `workflow_name` on `AgentDef` → Task 1
- ✅ `event_trigger` on workflow JSON → Task 2
- ✅ `llm` step type → Task 3
- ✅ `agent` step type → Task 3
- ✅ Workflow-backed custom agent → Task 4
- ✅ `KeyError` for missing workflow → Task 4
- ✅ `core/event_triggers.py` → Task 5
- ✅ `setup_event_triggers()` in `create_app()` → Task 5
- ✅ API: `event_trigger` on workflow → Task 6
- ✅ API: `workflow_name` on agent → Task 6
- ✅ Dashboard UI: all fields → Task 7
- ✅ `dry_run_workflow` new step types → Task 3

**All spec tests accounted for:**
- `test_workflow_store_steps.py` — 9 tests → Task 3 ✅
- `test_workflow_backed_agent.py` — 5 tests → Task 4 ✅
- `test_event_triggers.py` — 5 tests → Task 5 ✅
- `test_workflow_event_trigger_api.py` — 5 tests → Task 6 ✅
- Agent store additions — 2 tests → Task 1 ✅
- Workflow store additions — 2 tests → Task 2 ✅
