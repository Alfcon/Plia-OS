# Agent Builder Phase 3 Design

**Date:** 2026-06-29
**Status:** Approved

---

## Goal

Three capabilities that complete the custom agent and workflow engine:

1. **Tool execution in custom agents** — custom agents can call their registered tools (fixes the Phase 1 stub)
2. **Workflow variables** — steps declare a `name`; later steps reference `{{steps.name.result}}` or `{{steps.name.error}}`
3. **Workflow `if` step type** — conditional branching using structured conditions evaluated against step outputs

---

## Architecture

Approach: extend in place. Three files change, three test files are new.

| File | Change |
|------|--------|
| `agents/custom_agent.py` | Replace one-shot LLM call with tool-call loop |
| `agents/workflow_store.py` | Add variable tracking, extend `_interpolate`, add `if` step type + `_evaluate_condition` |
| `dashboard/static/index.html` | Step name field, `if` step UI, variable picker |
| `tests/test_custom_agent_tools.py` | NEW — 5 tests |
| `tests/test_workflow_variables.py` | NEW — 4 tests |
| `tests/test_workflow_if.py` | NEW — 5 tests |

---

## Section 1: Tool Execution in Custom Agents

### Current state

`custom_agent_node` calls the LLM once. If the LLM returns `tool_calls`, it drops a stub:
```
[Custom agent attempted a tool call but tool execution is not yet supported in Phase 1.]
```

### Design

Replace with a loop identical in structure to `respond_node`'s tool-call loop.

Module-level constant:
```python
_TOOL_CALL_LIMIT = 5
```

LLM path in `custom_agent_node` (after the `workflow_name` branch):
```python
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

`core.registry` is already imported at module level in `custom_agent.py`. The `workflow_name` branch is unchanged.

### Tests (`tests/test_custom_agent_tools.py`)

1. Tool call executed and result returned in `tool_results`
2. Multi-turn tool loop: LLM calls tool, gets result, calls tool again, then replies — all three turns complete
3. Tool raises exception → error string returned, agent continues
4. No-tools path (agent with no `tool_names`): unchanged behavior
5. `_TOOL_CALL_LIMIT` hit → fallback message returned, no exception

---

## Section 2: Workflow Variables

### Design

Steps accept an optional `"name"` field. `run_workflow` maintains a `variables: dict[str, dict]` as steps complete. `_interpolate` is extended to resolve `{{steps.name.result}}` and `{{steps.name.error}}`.

**Step JSON (name is optional):**
```json
{"name": "fetch", "step_type": "tool", "tool": "search_web", "params": {"query": "plia os"}}
```

**`_interpolate` signature change** (backward-compat — `variables` defaults to `None`):
```python
import re

def _interpolate(text: str, prev: str, variables: dict | None = None) -> str:
    text = text.replace("{{prev}}", prev)
    if variables:
        def _replace(m):
            return variables.get(m.group(1), {}).get(m.group(2), "")
        text = re.sub(r"\{\{steps\.(\w+)\.(result|error)\}\}", _replace, text)
    return text
```

**`run_workflow` internal additions:**
```python
variables: dict[str, dict] = {}

# after each step completes, inside the loop:
if step_name := step.get("name"):
    variables[step_name] = {
        "result": step_result.get("result") or "",
        "error": step_result.get("error") or "",
    }
```

`variables` is passed into every `_run_step` call so branch steps (inside `if`) can reference parent-scope named outputs.

### Tests (`tests/test_workflow_variables.py`)

1. Named step result stored and accessible in `variables`
2. `{{steps.name.result}}` interpolated correctly in a subsequent step's params
3. `{{steps.name.error}}` interpolated when step has an error
4. Unnamed steps not present in `variables`; `{{prev}}` still works unchanged

---

## Section 3: `if` Step Type

### Design

**Step JSON:**
```json
{
  "step_type": "if",
  "name": "branch",
  "condition": {
    "op": "contains",
    "value": "error"
  },
  "then": [
    {"step_type": "tool", "tool": "notify", "params": {"message": "{{prev}}"}}
  ],
  "else": [
    {"step_type": "llm", "prompt": "Summarize: {{prev}}"}
  ]
}
```

`else` is optional. If absent and condition is false, the `if` step returns `prev` unchanged.

**Supported ops:**

| Op | Meaning |
|----|---------|
| `eq` | `actual == value` |
| `ne` | `actual != value` |
| `contains` | `value in actual` |
| `not_contains` | `value not in actual` |
| `empty` | `not actual.strip()` |
| `not_empty` | `bool(actual.strip())` |

The condition is always evaluated against `prev` (the result string of the immediately preceding step). To condition on a specific named step's output, reference it via `{{steps.name.result}}` in a prior step and let it flow through as `prev`.

**`_evaluate_condition` helper:**
```python
def _evaluate_condition(condition: dict, prev: str) -> bool:
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

**`_run_step` signature change:**

`_run_step` gains a third parameter: `_run_step(step: dict, prev: str, variables: dict) -> dict`. All internal callers updated. Backward-compat not required — `_run_step` is module-private.

**`_run_step` `if` branch:**

The `if` step runs branch steps inline using recursive `_run_step` calls. Branch steps share the parent `variables` dict (mutable, so named outputs from branch steps are visible to subsequent main-flow steps). The `if` step's result is the final branch step's result (or `prev` if no branch runs).

The workflow result list includes the `if` step entry with a `"sub_steps"` key containing branch step results.

**`dry_run_workflow`** describes `if` steps as: `"[if] <op> <value> → then: N steps / else: M steps"`.

### Tests (`tests/test_workflow_if.py`)

1. Condition true → `then` branch executes, result returned
2. Condition false → `else` branch executes, result returned
3. Condition false, no `else` → `prev` returned unchanged
4. Condition ops: `contains`, `eq`, `empty` each evaluated correctly
5. Branch step can reference parent `variables` via `{{steps.name.result}}`

---

## Section 4: Dashboard UI

All changes in `dashboard/static/index.html`.

### Step name field

Added above the step-type selector on every step card:
```html
<input class="wf-step-name" placeholder="Step name (optional, for {{steps.name.result}})" ...>
```

`_wfCollectSteps()` serializes it as `"name"` if non-empty. `wfLoad()` populates it from `step.name`. `wfNew()` and step-reset paths clear it.

### `if` step type

New `"if"` option in the step-type `<select>`. Selecting `"if"` hides `.wf-tool-fields`, `.wf-llm-fields`, `.wf-agent-fields` and shows `.wf-if-fields`:

```html
<div class="wf-if-fields" style="display:none">
  <!-- condition builder -->
  <select class="wf-if-op">
    <option value="not_empty">is not empty</option>
    <option value="empty">is empty</option>
    <option value="contains">contains</option>
    <option value="not_contains">does not contain</option>
    <option value="eq">equals</option>
    <option value="ne">does not equal</option>
  </select>
  <input class="wf-if-value" placeholder="value">
  <!-- branch editors -->
  <label>then (JSON step array):</label>
  <textarea class="wf-if-then" rows="4" placeholder='[{"step_type":"tool",...}]'></textarea>
  <label>else (JSON step array, optional):</label>
  <textarea class="wf-if-else" rows="4" placeholder='[{"step_type":"llm",...}]'></textarea>
</div>
```

`_wfCollectSteps()` serializes `condition`, `then` (JSON.parse), `else` (JSON.parse, omitted if empty). `wfLoad()` populates condition fields and branch textareas from step JSON.

### Variable picker

Below the params field on tool/llm/agent steps, a read-only hint `<div>` lists `{{steps.X.result}}` for all named steps defined earlier in the current form. Updates as step names are typed. Clicking a reference copies it to clipboard.

---

## Backward Compatibility

- Existing tool steps (no `name`, no `step_type`) — unchanged
- `_interpolate(text, prev)` — still valid; `variables` parameter optional
- `run_workflow` signature — unchanged
- `dry_run_workflow` — `if` step gets a new display path; all others unchanged
- All existing tests must pass

---

## Global Constraints

- No new pip dependencies
- `_TOOL_CALL_LIMIT = 5` in `custom_agent.py` (matches `respond_node`)
- `_evaluate_condition` is a pure function — no I/O, no LLM calls
- `variables` dict is passed by reference through `_run_step`; branch steps mutate the parent scope intentionally
- `then`/`else` branch step lists in the UI are raw JSON textareas (no recursive builder)
- All tests use project patterns: `AsyncClient(transport=ASGITransport(app=create_app()))` for API tests; direct function calls for unit tests
