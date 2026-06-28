from __future__ import annotations

import json
import time
from pathlib import Path


def _path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir).expanduser() / "prompts.json"


def _load() -> dict[str, dict]:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def list_prompts() -> list[dict]:
    data = _load()
    return sorted(
        [{"name": k, **v} for k, v in data.items()],
        key=lambda x: x.get("created_at", 0),
        reverse=True,
    )


def get_prompt(name: str) -> dict | None:
    data = _load()
    if name not in data:
        return None
    return {"name": name, **data[name]}


def save_prompt(name: str, text: str, description: str = "") -> None:
    if not name or not name.strip():
        raise ValueError("name required")
    if not text or not text.strip():
        raise ValueError("text required")
    name = name.strip()
    data = _load()
    data[name] = {
        "text": text.strip(),
        "description": description.strip(),
        "created_at": data.get(name, {}).get("created_at", int(time.time())),
        "updated_at": int(time.time()),
    }
    _save(data)


def delete_prompt(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True
