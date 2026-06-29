# Agent Builder — Phase 2: Workflow Agents

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend custom agents and workflows with three capabilities: (1) a custom agent can delegate to a named workflow instead of calling the LLM directly; (2) workflows can contain `llm` and `agent` step types alongside existing `tool` steps; (3) a workflow can subscribe to a Plia event type and fire automatically when that event fires.

**Phase:** 2 of 2. Builds on Phase 1 (committed). No new dependencies.

**Architecture:** Approach A — extend in place. `run_workflow` gains `llm`/`agent` step dispatch. `AgentDef` gains `workflow_name`. A thin `core/event_triggers.py` subscribes to the event bus. Dashboard Flows panel and Custom Agents panel get targeted additions.

**Tech Stack:** FastAPI, LangGraph, Python dataclasses, asyncio, JSON file store.

---

## Global Constraints

- No new pip dependencies
- `run_workflow` already async — stays async
- Backward compat: existing workflow steps (no `step_type` key, has `"tool"` key) execute unchanged
- `workflow_name` on `AgentDef` is optional (`None` = Phase 1 LLM behavior)
- `event_trigger` on workflow is optional (`None`/absent = no auto-fire)
- Circular import `workflow_store ↔ custom_agent` broken with late imports inside function bodies
- All tests use `AsyncClient(transport=ASGITransport(app=create_app()))` per project convention
- Mock `call_llm` via `patch("agents.llm.call_llm")`
- `AgentDef.workflow_name` field added via `core/agent_store.py` only — no other file needs to know the field exists to remain correct

---

## Data Model

### `AgentDef` — new field

```python
# core/agent_store.py
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
    workflow_name: str | None = None   # NEW — None = LLM-backed (Phase 1)
```

When `workflow_name` is set, `custom_agent_node` runs the named workflow instead of calling the LLM. `system_prompt`, `tool_names`, and `llm_description` are still persisted but ignored at runtime while `workflow_name` is set.

### Workflow JSON — new field

```json
{
  "my-workflow": {
    "description": "...",
    "steps": [...],
    "event_trigger": "reminder_fired"
  }
}
```

`event_trigger` is optional. Absent or `null` = no auto-fire. Value is an exact event type string (e.g., `reminder_fired`, `status`, `agent_routing`).

`save_workflow` signature extended:
```python
def save_workflow(
    name: str,
    steps: list[dict],
    description: str = "",
    event_trigger: str | None = None,
) -> None:
```

Always writes `event_trigger` key (value may be `None`) so `list_workflows()` returns it consistently.

### Step format — new `step_type` discriminator

Existing steps have no `step_type` key. Detection rule:

```python
step_type = step.get("step_type", "tool")
```

Three values:

```json
{"tool": "web_search", "params": {"q": "{{prev}}"}, "note": "..."}

{"step_type": "llm", "prompt": "Summarize: {{prev}}", "system": "Be concise."}

{"step_type": "agent", "name": "finance", "message": "{{prev}}"}
```

All string fields support existing template vars: `{{prev}}`, `{{step_N}}`, `{{payload}}`, `{{payload.key}}`, `{{vars.name}}`.

---

## Components

### `core/agent_store.py` (modified)

Add `workflow_name: str | None = None` to `AgentDef`. No other changes — `save_agent`/`get_agent`/`list_agents` handle new field automatically via `dataclasses.asdict` / `**data` unpacking.

### `agents/workflow_store.py` (modified)

**`save_workflow`** — add `event_trigger` param, always write it to JSON entry.

**`_run_step` (new private helper):**

```python
async def _run_step(
    step: dict,
    step_results: list[str],
    payload: dict | None,
) -> tuple[str, str | None]:
    """Returns (result_str, error_str | None)."""
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

**`run_workflow`** — replace inline tool dispatch with `_run_step` call. Output dict gains `"step_type"` key echoing the dispatched type.

**`dry_run_workflow`** — matching dispatch: `llm` → `[DRY RUN] would call LLM with prompt: <interpolated>`, `agent` → `[DRY RUN] would call agent '<name>' with: <message>`, `tool` → existing string.

### `agents/custom_agent.py` (modified)

Add workflow path before existing LLM path:

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

    # existing LLM path unchanged
    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    ...
```

User message passed as `{{payload.message}}` within workflow steps.

### `core/event_triggers.py` (new)

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

Subscriber receives `{"type": event_type, **data}` — `payload["type"]` is the event type string. Exceptions per workflow are caught and logged; other workflows in the same event still run.

### `core/main.py` (modified)

Call `setup_event_triggers()` in lifespan alongside existing `setup_event_forwarding()`:

```python
from core.event_triggers import setup_event_triggers
# in lifespan or create_app:
setup_event_triggers()
```

### `dashboard/server.py` (modified)

**`POST /api/workflows`** — add `event_trigger` extraction:
```python
event_trigger = (body.get("event_trigger") or "").strip() or None
await asyncio.to_thread(save_workflow, name, steps, description, event_trigger=event_trigger)
```

**`POST /api/agents`** — add `workflow_name`:
```python
workflow_name = (body.get("workflow_name") or "").strip() or None
defn = AgentDef(..., workflow_name=workflow_name)
```

**`PUT /api/agents/{name}`** — same, preserve `created_at` as before.

### `dashboard/static/index.html` (modified)

**Flows panel — step editor:**

Add `step_type` `<select>` above existing step fields (options: `tool`, `llm`, `agent`). On change, show/hide field groups:
- `tool`: existing `tool` input + `params` JSON editor
- `llm`: `prompt` textarea + optional `system` text input
- `agent`: `name` text input (slug) + `message` text input (default `{{prev}}`)

Step load/save reads/writes `step_type` alongside existing fields.

**Flows panel — workflow form:**

Add `event_trigger` text input below description. Placeholder: `reminder_fired` (leave blank for none). Populated on workflow load, included in save body.

**Custom Agents panel — agent form:**

Add `workflow_name` `<select>` populated from `GET /api/workflows` on panel load and form open. Options: empty option "None (LLM-backed)" + one option per workflow. When a workflow is selected, system_prompt/tool_names sections get `opacity: 0.4` and a note "Overridden by workflow at runtime". Save sends `workflow_name: selectedValue || null`.

---

## API Contracts

### `POST /api/workflows`

New optional field:
```json
{
  "name": "daily-brief",
  "description": "Morning briefing",
  "steps": [...],
  "event_trigger": "reminder_fired"
}
```

`event_trigger` absent or `""` → stored as `null`.

### `POST /api/agents` / `PUT /api/agents/{name}`

New optional field:
```json
{
  "name": "briefer",
  "display_name": "Daily Briefer",
  "system_prompt": "...",
  "tool_names": [],
  "keywords": ["brief"],
  "llm_description": "Use for daily briefings",
  "enabled": true,
  "workflow_name": "daily-brief"
}
```

`workflow_name` absent or `""` → stored as `null`.

---

## Testing

### `tests/test_workflow_store_steps.py`

```python
# llm step calls call_llm with interpolated prompt
async def test_llm_step_calls_llm():
    save_workflow("w", [{"step_type": "llm", "prompt": "Say hi"}])
    mock_llm = AsyncMock(return_value={"content": "Hello"})
    with patch("agents.llm.call_llm", mock_llm):
        output = await run_workflow("w")
    assert output[0]["result"] == "Hello"
    assert mock_llm.call_args[0][0][-1]["content"] == "Say hi"

# llm step interpolates {{prev}}
async def test_llm_step_interpolates_prev():
    save_workflow("w", [
        {"tool": "echo", "params": {"text": "world"}},
        {"step_type": "llm", "prompt": "Translate: {{prev}}"},
    ])
    with patch("core.registry.call_tool_async", AsyncMock(return_value="world")), \
         patch("agents.llm.call_llm", AsyncMock(return_value={"content": "monde"})) as m:
        await run_workflow("w")
    assert "world" in m.call_args[0][0][-1]["content"]

# agent step calls custom_agent_node
async def test_agent_step_calls_custom_agent():
    save_workflow("w", [{"step_type": "agent", "name": "finance", "message": "check AAPL"}])
    mock_node = AsyncMock(return_value={"tool_results": ["$200"]})
    with patch("agents.custom_agent.custom_agent_node", mock_node):
        output = await run_workflow("w")
    assert output[0]["result"] == "$200"
    assert mock_node.call_args[0][0]["active_agent"] == "custom:finance"

# tool step unchanged (backward compat)
async def test_tool_step_backward_compat():
    save_workflow("w", [{"tool": "calculate", "params": {"expr": "2+2"}}])
    with patch("core.registry.call_tool_async", AsyncMock(return_value=4)):
        output = await run_workflow("w")
    assert output[0]["result"] == "4"

# dry_run for llm step
async def test_dry_run_llm_step():
    save_workflow("w", [{"step_type": "llm", "prompt": "hi"}])
    output = await dry_run_workflow("w")
    assert "DRY RUN" in output[0]["result"]
    assert "LLM" in output[0]["result"]

# dry_run for agent step
async def test_dry_run_agent_step():
    save_workflow("w", [{"step_type": "agent", "name": "finance", "message": "check"}])
    output = await dry_run_workflow("w")
    assert "DRY RUN" in output[0]["result"]
    assert "finance" in output[0]["result"]

# unknown step_type surfaces error, stops workflow
async def test_unknown_step_type_error():
    save_workflow("w", [{"step_type": "zap", "foo": "bar"}])
    output = await run_workflow("w")
    assert output[0]["error"] is not None
    assert "Unknown step_type" in output[0]["error"]
```

### `tests/test_workflow_backed_agent.py`

```python
# custom_agent_node routes to run_workflow when workflow_name set
async def test_workflow_name_routes_to_run_workflow(mock_store):
    save_agent(_defn(workflow_name="my-wf"))
    mock_run = AsyncMock(return_value=[{"result": "workflow output", "error": None}])
    with patch("agents.workflow_store.run_workflow", mock_run):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == ["workflow output"]
    mock_run.assert_called_once_with("my-wf", payload={"message": "what is AAPL stock"})

# workflow error surfaces in tool_results
async def test_workflow_error_surfaced(mock_store):
    save_agent(_defn(workflow_name="bad-wf"))
    mock_run = AsyncMock(return_value=[{"result": "", "error": "tool not found"}])
    with patch("agents.workflow_store.run_workflow", mock_run):
        result = await custom_agent_node(_state("custom:finance"))
    assert "Workflow error" in result["tool_results"][0]

# no workflow_name → existing LLM path unchanged
async def test_no_workflow_name_uses_llm(mock_store):
    save_agent(_defn(workflow_name=None))
    mock_llm = AsyncMock(return_value={"content": "result"})
    with patch("agents.llm.call_llm", mock_llm):
        result = await custom_agent_node(_state("custom:finance"))
    mock_llm.assert_called_once()
    assert result["tool_results"] == ["result"]

# empty workflow output returns empty string
async def test_empty_workflow_output(mock_store):
    save_agent(_defn(workflow_name="empty-wf"))
    with patch("agents.workflow_store.run_workflow", AsyncMock(return_value=[])):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == [""]

# missing workflow name (KeyError) returns friendly error
async def test_missing_workflow_returns_error(mock_store):
    save_agent(_defn(workflow_name="missing-wf"))
    with patch("agents.workflow_store.run_workflow", AsyncMock(side_effect=KeyError("missing-wf"))):
        result = await custom_agent_node(_state("custom:finance"))
    assert "not found" in result["tool_results"][0]
```

### `tests/test_event_triggers.py`

```python
# setup_event_triggers subscribes _on_event to event bus
def test_setup_subscribes():
    from core.event_triggers import setup_event_triggers, _on_event
    setup_event_triggers()
    assert events.is_subscribed(_on_event)

# matching event fires workflow
async def test_matching_event_fires_workflow(tmp_path):
    # isolate_config_file autouse fixture redirects _CONFIG_FILE to tmp;
    # _workflows_path() derives from get_config().memory_dir, so no extra patch needed.
    save_workflow("brief", [{"tool": "noop", "params": {}}], event_trigger="reminder_fired")
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        await events.emit("reminder_fired", {"msg": "time to brief"})
    mock_run.assert_called_once_with("brief", payload={"type": "reminder_fired", "msg": "time to brief"})

# non-matching event ignored
async def test_non_matching_event_ignored(tmp_path):
    save_workflow("brief", [...], event_trigger="reminder_fired")
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        await events.emit("status", {"state": "armed"})
    mock_run.assert_not_called()

# exception in workflow is caught, does not propagate
async def test_workflow_exception_caught(tmp_path):
    save_workflow("bad", [...], event_trigger="reminder_fired")
    with patch("agents.workflow_store.run_workflow", AsyncMock(side_effect=RuntimeError("boom"))):
        await events.emit("reminder_fired", {})  # should not raise
```

### `tests/test_workflow_event_trigger_api.py`

```python
# POST /api/workflows with event_trigger saves and returns it
async def test_save_workflow_with_event_trigger(client):
    resp = await client.post("/api/workflows", json={
        "name": "test-wf", "steps": [], "event_trigger": "reminder_fired"
    })
    assert resp.status_code == 200
    wfs = (await client.get("/api/workflows")).json()["workflows"]
    match = next(w for w in wfs if w["name"] == "test-wf")
    assert match["event_trigger"] == "reminder_fired"

# POST /api/agents with workflow_name roundtrips
async def test_create_agent_with_workflow_name(client):
    resp = await client.post("/api/agents", json={
        "name": "briefer", "display_name": "Briefer",
        "system_prompt": "...", "tool_names": [], "keywords": [],
        "llm_description": "", "workflow_name": "daily-brief"
    })
    assert resp.status_code == 201
    assert resp.json()["workflow_name"] == "daily-brief"

# PUT /api/agents/{name} updates workflow_name
async def test_update_agent_workflow_name(client):
    await client.post("/api/agents", json={...})  # create first
    resp = await client.put("/api/agents/briefer", json={..., "workflow_name": "new-wf"})
    assert resp.json()["workflow_name"] == "new-wf"

# workflow_name absent → null
async def test_workflow_name_defaults_null(client):
    resp = await client.post("/api/agents", json={
        "name": "plain", "display_name": "Plain", "system_prompt": "...",
        "tool_names": [], "keywords": [], "llm_description": ""
    })
    assert resp.json()["workflow_name"] is None
```

---

## Out of Scope

- Agent-to-agent chaining beyond one `agent` step (no recursion guard needed yet — `agent` step creates a fresh state, no cycle detection)
- Event trigger filtering / conditions (exact type match only)
- Event trigger rate-limiting or debouncing
- Schedule triggers (cron already exists separately)
- Workflow versioning / history
- Custom agent versioning
