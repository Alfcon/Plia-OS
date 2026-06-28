from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.registry import call_tool_async


def _webhooks_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / "webhooks.json"


def _load() -> dict[str, dict]:
    p = _webhooks_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, dict]) -> None:
    p = _webhooks_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def list_webhooks() -> list[dict]:
    data = _load()
    return [{"slug": k, **v} for k, v in data.items()]


def get_webhook(slug: str) -> dict | None:
    data = _load()
    if slug not in data:
        return None
    return {"slug": slug, **data[slug]}


def save_webhook(
    slug: str,
    *,
    name: str = "",
    target_type: str = "workflow",
    target: str,
    params: dict | None = None,
    description: str = "",
    secret: str = "",
) -> None:
    data = _load()
    data[slug] = {
        "name": name or slug,
        "target_type": target_type,
        "target": target,
        "params": params or {},
        "description": description,
        "secret": secret,
        "created_at": data.get(slug, {}).get("created_at", int(time.time())),
    }
    _save(data)


def delete_webhook(slug: str) -> bool:
    data = _load()
    if slug not in data:
        return False
    del data[slug]
    _save(data)
    return True


async def fire_webhook(slug: str, payload: dict) -> dict:
    from agents.workflow_store import run_workflow

    wh = get_webhook(slug)
    if wh is None:
        raise KeyError(f"Webhook {slug!r} not found")

    target_type = wh.get("target_type", "workflow")
    target = wh.get("target", "")

    if target_type == "workflow":
        steps = await run_workflow(target, payload=payload)
        last = steps[-1]["result"] if steps else ""
        error = next((s["error"] for s in steps if s["error"]), None)
        return {"ok": error is None, "type": "workflow", "steps": steps, "result": last, "error": error}

    if target_type == "tool":
        from agents.workflow_store import _interpolate_params
        raw_params = dict(wh.get("params", {}))
        merged = {**raw_params, **payload}
        params = _interpolate_params(merged, [], payload)
        try:
            result = await call_tool_async(target, params)
            return {"ok": True, "type": "tool", "result": str(result), "error": None}
        except Exception as exc:
            return {"ok": False, "type": "tool", "result": "", "error": str(exc)}

    raise ValueError(f"Unknown target_type: {target_type!r}")
