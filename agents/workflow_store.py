from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import time
from pathlib import Path
from typing import Any

_wf_depth: contextvars.ContextVar[int] = contextvars.ContextVar("_wf_depth", default=0)


def _workflows_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / "workflows.json"


def _load() -> dict[str, dict]:
    p = _workflows_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, dict]) -> None:
    p = _workflows_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def list_workflows() -> list[dict]:
    data = _load()
    return [{"name": k, **v} for k, v in data.items()]


def get_workflow(name: str) -> dict | None:
    data = _load()
    if name not in data:
        return None
    return {"name": name, **data[name]}


def save_workflow(
    name: str,
    steps: list[dict],
    description: str = "",
    event_trigger: str | None = None,
) -> None:
    data = _load()
    data[name] = {"description": description, "steps": steps, "event_trigger": event_trigger}
    _save(data)


def delete_workflow(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True


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


def _interpolate_params(params: dict, results: list[str], payload: dict | None = None, run_vars: dict[str, dict] | None = None) -> dict:
    return {k: _interpolate(v, results, payload, run_vars) for k, v in params.items()}


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


from core.registry import call_tool_async


async def _run_step(
    step: dict,
    step_results: list[str],
    payload: dict | None,
    run_vars: dict[str, dict] | None = None,
) -> tuple[str, str | None, list[dict]]:
    """Dispatch one workflow step. Returns (result_str, error_str | None, sub_steps)."""
    step_type = step.get("step_type", "tool")

    if step_type == "tool":
        tool = step.get("tool", "")
        params = _interpolate_params(step.get("params", {}), step_results, payload, run_vars)
        result = await call_tool_async(tool, params)
        return str(result), None, []

    elif step_type == "llm":
        prompt = _interpolate(step.get("prompt", ""), step_results, payload, run_vars)
        system = step.get("system", "")
        msgs = ([{"role": "system", "content": system}] if system else [])
        msgs.append({"role": "user", "content": prompt})
        import agents.llm
        msg = await agents.llm.call_llm(msgs)
        return msg.get("content") or "", None, []

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
        return results_list[0] if results_list else "", None, []

    elif step_type == "if":
        prev = step_results[-1] if step_results else ""
        condition = step.get("condition", {})
        branch = step.get("then", []) if _evaluate_condition(condition, prev) else step.get("else", [])
        sub_step_results = list(step_results)  # copy — sub-steps see parent results but don't pollute index
        branch_prev = prev
        sub_steps: list[dict] = []
        for i, sub_step in enumerate(branch):
            sub_result, sub_error, _ = await _run_step(sub_step, sub_step_results, payload, run_vars)
            sub_steps.append({
                "step": i,
                "step_type": sub_step.get("step_type", "tool"),
                "result": sub_result,
                "error": sub_error,
            })
            sub_step_results.append(sub_result)
            if run_vars is not None and (sub_name := sub_step.get("name")):
                run_vars[sub_name] = {"result": sub_result, "error": sub_error or ""}
            if sub_error:
                return sub_result, sub_error, sub_steps
            branch_prev = sub_result
        return branch_prev, None, sub_steps

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

    else:
        return "", f"Unknown step_type: {step_type!r}", []


async def run_workflow(name: str, payload: dict | None = None) -> list[dict]:
    depth = _wf_depth.get()
    if depth >= 10:
        raise RuntimeError(f"Workflow recursion depth limit reached (name={name!r})")
    token = _wf_depth.set(depth + 1)
    try:
        wf = get_workflow(name)
        if wf is None:
            raise KeyError(f"Workflow {name!r} not found")

        step_results: list[str] = []
        run_vars: dict[str, dict] = {}
        output: list[dict] = []

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
                elif step.get("continue_on_error"):
                    # No on_error fallback, but continue_on_error is True: use error as result
                    result_str = error
                    error = None

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

        return output
    finally:
        _wf_depth.reset(token)


async def dry_run_workflow(name: str, payload: dict | None = None) -> list[dict]:
    """Simulate a workflow run without executing tool calls."""
    wf = get_workflow(name)
    if wf is None:
        raise KeyError(f"Workflow {name!r} not found")

    step_results: list[str] = []
    run_vars: dict[str, dict] = {}
    output: list[dict] = []

    for i, step in enumerate(wf["steps"]):
        step_type = step.get("step_type", "tool")
        tool = step.get("tool", "")
        raw_params = step.get("params", {})
        note = step.get("note", "")
        params = _interpolate_params(raw_params, step_results, payload, run_vars)

        if step_type == "llm":
            prompt = _interpolate(step.get("prompt", ""), step_results, payload, run_vars)
            dry_result = f"[DRY RUN] would call LLM with prompt: {prompt!r}"
        elif step_type == "agent":
            agent_name = step.get("name", "")
            message = _interpolate(step.get("message", "{{prev}}"), step_results, payload, run_vars)
            dry_result = f"[DRY RUN] would call agent {agent_name!r} with: {message!r}"
        elif step_type == "if":
            condition = step.get("condition", {})
            op = condition.get("op", "not_empty")
            value = condition.get("value", "")
            then_n = len(step.get("then", []))
            else_n = len(step.get("else", []))
            dry_result = f"[DRY RUN] [if] {op} {value!r} → then: {then_n} steps / else: {else_n} steps"
        elif step_type == "parallel":
            branches = step.get("branches", [])
            branch_names = ", ".join(b.get("name", "?") for b in branches)
            dry_result = f"[DRY RUN] parallel: {len(branches)} branches ({branch_names})"
        elif step_type == "workflow":
            wf_name = step.get("workflow_name", "")
            params = _interpolate_params(step.get("params", {}), step_results, payload, run_vars)
            dry_result = f"[DRY RUN] would call workflow {wf_name!r} with {params}"
        else:
            dry_result = f"[DRY RUN] would call {tool!r} with {params}"

        step_results.append(dry_result)
        if step_name := step.get("name"):
            run_vars[step_name] = {"result": dry_result, "error": ""}
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
