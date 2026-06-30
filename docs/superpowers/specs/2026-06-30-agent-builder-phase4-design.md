# Agent Builder Phase 4 Design

**Date:** 2026-06-30
**Status:** Approved

---

## Goal

Three capabilities that extend the workflow engine beyond linear step sequences:

1. **Parallel step** — run multiple step-lists concurrently, collect all results
2. **Error handling** — per-step `continue_on_error` flag and `on_error` fallback steps
3. **Subworkflow step** — call another named workflow as a step with a custom payload

---

## Architecture

Approach: extend in place. Two files change, four test files are new.

| File | Change |
|------|--------|
| `agents/workflow_store.py` | Add `parallel`, `workflow`, and error-handling logic to `_run_step` and `run_workflow` |
| `dashboard/static/index.html` | Parallel branch editor, error-handling inputs, subworkflow fields |
| `tests/test_workflow_parallel.py` | NEW — 5 tests |
| `tests/test_workflow_error_handling.py` | NEW — 5 tests |
| `tests/test_workflow_subworkflow.py` | NEW — 4 tests |

---

## Section 1: Parallel Step

### Step JSON

```json
{
  "step_type": "parallel",
  "name": "gather",
  "branches": [
    {"name": "weather", "steps": [{"step_type": "tool", "tool": "get_weather", "params": {}}]},
    {"name": "news",    "steps": [{"step_type": "tool", "tool": "search_web",  "params": {"query": "news"}}]}
  ]
}
```

### Behaviour

All branches run concurrently via `asyncio.gather`. Each branch runs its steps sequentially with its own `sub_step_results` (copy of parent `step_results` at the time the parallel step runs). All branches share the parent `run_vars` dict (by reference), so named sub-steps within branches are visible to subsequent main-flow steps.

After all branches complete:
- Each branch's final result (or error string) is stored in `run_vars` under the branch name: `run_vars[branch_name] = {"result": ..., "error": ...}`
- `{{prev}}` (the parallel step's result) = `json.dumps([branch_results_in_order])` — a JSON array of the final result strings
- If a branch raises an exception or its last sub-step errors, its entry in the array is the error string; the parallel step itself does NOT stop the workflow — branch errors are captured, not propagated

### `_run_step` parallel branch

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
    results_list = []
    for item in gathered:
        if isinstance(item, Exception):
            results_list.append(str(item))
        else:
            branch_name, branch_result, branch_error = item
            if run_vars is not None and branch_name:
                run_vars[branch_name] = {"result": branch_result, "error": branch_error}
            results_list.append(branch_result if not branch_error else branch_error)
    import json as _json
    return _json.dumps(results_list), None, []
```

### `dry_run_workflow`

Parallel step dry-run result: `f"[DRY RUN] parallel: {len(branches)} branches ({', '.join(b.get('name','?') for b in branches)})"`

### Tests (`tests/test_workflow_parallel.py`)

1. All branches complete → `{{prev}}` is JSON array in branch order
2. Branch error captured in array, workflow continues (no stop)
3. Branch named results stored in `run_vars`
4. Branches run concurrently — both branches called within same asyncio tick (mock with event/future)
5. `dry_run_workflow` describes parallel step correctly

---

## Section 2: Error Handling

### Per-step fields (optional, any step type)

```json
{
  "step_type": "tool",
  "tool": "fetch_url",
  "params": {"url": "{{payload.url}}"},
  "continue_on_error": true,
  "on_error": [
    {"step_type": "llm", "prompt": "Could not fetch URL. Say so briefly."}
  ]
}
```

### Behaviour

**`continue_on_error: true`** — if the step fails, execution continues to the next step. `{{prev}}` receives the error string. The step's `run_vars` entry (if named) gets `{"result": "", "error": "..."}`.

**`on_error: [{...steps...}]`** — if the step fails, run this list of fallback steps sequentially (sharing parent `run_vars`, using a copy of `step_results`). The fallback's final result becomes the step's result. Execution continues normally after. If a fallback step itself errors, that error propagates as the step's error (unless `continue_on_error` is also set).

**Precedence:** if both flags are set, `on_error` runs first. If the fallback succeeds, result is used and execution continues. `continue_on_error` acts as a safety net if the fallback also fails.

**Default:** current stop-on-error behaviour is unchanged when neither flag is set.

### Implementation in `run_workflow`

After `_run_step` returns an error:
```python
if error:
    if step.get("on_error"):
        # run fallback steps
        fallback_results = list(step_results)
        fallback_prev = ""
        fallback_error = error
        for fb_step in step["on_error"]:
            fb_result, fb_error, _ = await _run_step(fb_step, fallback_results, payload, run_vars)
            fallback_results.append(fb_result)
            if fb_error:
                fallback_error = fb_error
                break
            fallback_prev = fb_result
            fallback_error = None
        result_str = fallback_prev
        error = fallback_error
    if error and not step.get("continue_on_error"):
        break  # stop workflow
    # else: continue with result_str (error string or fallback result)
```

### Tests (`tests/test_workflow_error_handling.py`)

1. `continue_on_error: true` → workflow continues, `{{prev}}` gets error string
2. `on_error` fallback runs on failure, fallback result replaces errored step
3. `on_error` fallback result stored in `run_vars` under step name
4. Neither flag → stop-on-error unchanged
5. Both flags set: `on_error` runs; if fallback also fails, `continue_on_error` allows continuation

---

## Section 3: Subworkflow Step

### Step JSON

```json
{
  "step_type": "workflow",
  "name": "sub",
  "workflow_name": "fetch_and_summarize",
  "params": {
    "url": "{{payload.url}}",
    "topic": "{{steps.classify.result}}"
  }
}
```

### Behaviour

`params` is interpolated (via `_interpolate_params`) then passed as the child workflow's payload dict. Child runs via `run_workflow(workflow_name, payload=interpolated_params)`. The existing `_wf_depth` ContextVar recursion guard (depth ≥ 10 → `RuntimeError`) already covers infinite loops.

Result = child workflow's last step's `"result"` value. Error = child workflow's last step's `"error"` value, or the recursion-limit `RuntimeError` message, or a `KeyError` if the workflow name doesn't exist.

The child's internal `run_vars` are isolated — they do not leak into the parent scope.

### `_run_step` workflow branch

```python
elif step_type == "workflow":
    workflow_name = step.get("workflow_name", "")
    params = _interpolate_params(step.get("params", {}), step_results, payload, run_vars)
    child_output = await run_workflow(workflow_name, payload=params)
    if not child_output:
        return "", "Subworkflow returned no output", []
    last = child_output[-1]
    if last.get("error"):
        return last.get("result", ""), last["error"], []
    return last.get("result", ""), None, []
```

### `dry_run_workflow`

Subworkflow dry-run result: `f"[DRY RUN] would call workflow {workflow_name!r} with {params}"`

### Tests (`tests/test_workflow_subworkflow.py`)

1. Child workflow called with interpolated params
2. Child result becomes step result in parent
3. Recursion guard triggers at depth 10 (mock `_wf_depth` or nest real workflows)
4. Child workflow error propagates as parent step error

---

## Section 4: Dashboard UI

All changes in `dashboard/static/index.html`.

### Parallel step

New `"parallel"` option in step-type `<select>`. Selecting `"parallel"` shows `.wf-parallel-fields`, hides all other field divs.

```html
<div class="wf-parallel-fields" style="display:none">
  <div class="wf-parallel-branches">
    <!-- dynamic branch rows added by JS -->
  </div>
  <button onclick="_wfAddBranch(this)">+ Add Branch</button>
</div>
```

Each branch row: name input + textarea for steps JSON array. `_wfCollectSteps()` serializes as `{step_type:"parallel", branches:[{name, steps:JSON.parse(textarea)}]}`. `wfLoad()` populates branch rows from `step.branches`.

### Error handling

On every step card, below existing type-specific fields, above the note field:

```html
<label><input type="checkbox" class="wf-continue-on-error"> Continue on error</label>
<label>On error (JSON step array):</label>
<textarea class="wf-on-error" rows="3" placeholder='[{"step_type":"llm",...}]'></textarea>
```

`_wfCollectSteps()`: sets `continue_on_error: true` if checkbox checked; sets `on_error: JSON.parse(...)` if textarea non-empty. `wfLoad()`: checks checkbox from `step.continue_on_error`; populates textarea from `step.on_error`.

### Subworkflow step

New `"workflow"` option in step-type `<select>`. Shows `.wf-workflow-fields`:

```html
<div class="wf-workflow-fields" style="display:none">
  <input class="wf-workflow-name" placeholder="Workflow name">
  <label>Params (JSON object):</label>
  <textarea class="wf-workflow-params" rows="3" placeholder='{"key": "{{prev}}"}'></textarea>
</div>
```

`_wfCollectSteps()`: serializes `{step_type:"workflow", workflow_name, params:JSON.parse(...)}`. `wfLoad()`: populates from `step.workflow_name` and `step.params`.

---

## Backward Compatibility

- Existing steps with no new fields — unchanged
- `_run_step` and `run_workflow` — no signature changes
- `continue_on_error`/`on_error` absent → existing stop-on-error behaviour
- All existing tests must pass

---

## Global Constraints

- No new pip dependencies
- `asyncio.gather` used for parallel branches — add `import asyncio` to `workflow_store.py` imports
- Recursion guard (`_wf_depth`) covers subworkflow nesting — no additional guard needed
- Branch `sub_step_results` is a copy; `run_vars` is shared (same as `if` step pattern)
- `on_error` fallback uses copy of `step_results`; `run_vars` is shared
- All tests use project patterns: direct `run_workflow` calls for unit tests
