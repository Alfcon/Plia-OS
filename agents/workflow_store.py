from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any


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


def save_workflow(name: str, steps: list[dict], description: str = "") -> None:
    data = _load()
    data[name] = {"description": description, "steps": steps}
    _save(data)


def delete_workflow(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True


def _interpolate(value: Any, results: list[str], payload: dict | None = None) -> Any:
    """Substitute {{prev}}, {{step_N}}, {{payload}}, {{payload.key}} in string values."""
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

    return value


def _interpolate_params(params: dict, results: list[str], payload: dict | None = None) -> dict:
    return {k: _interpolate(v, results, payload) for k, v in params.items()}


from core.registry import call_tool_async


async def run_workflow(name: str, payload: dict | None = None) -> list[dict]:
    wf = get_workflow(name)
    if wf is None:
        raise KeyError(f"Workflow {name!r} not found")

    step_results: list[str] = []
    output: list[dict] = []

    for i, step in enumerate(wf["steps"]):
        tool = step.get("tool", "")
        raw_params = step.get("params", {})
        note = step.get("note", "")
        params = _interpolate_params(raw_params, step_results, payload)
        t0 = time.monotonic()
        try:
            result = await call_tool_async(tool, params)
            result_str = str(result)
            error = None
        except Exception as exc:
            result_str = ""
            error = str(exc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        step_results.append(result_str)
        output.append({
            "step": i,
            "tool": tool,
            "params": params,
            "note": note,
            "result": result_str,
            "error": error,
            "duration_ms": duration_ms,
        })
        if error:
            break

    return output
