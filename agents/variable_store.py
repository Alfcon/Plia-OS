from __future__ import annotations

import json
import time
from pathlib import Path


def _vars_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / "variables.json"


def _load() -> dict[str, dict]:
    p = _vars_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, dict]) -> None:
    p = _vars_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def list_vars() -> list[dict]:
    data = _load()
    return [{"name": k, **v} for k, v in sorted(data.items())]


def get_var(name: str) -> str | None:
    data = _load()
    entry = data.get(name)
    return entry["value"] if entry else None


def set_var(name: str, value: str, description: str = "") -> None:
    data = _load()
    data[name] = {
        "value": value,
        "description": description,
        "updated_at": int(time.time()),
    }
    _save(data)


def delete_var(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True


def resolve_vars(text: str) -> str:
    """Replace {{vars.name}} in text with stored values."""
    import re

    def _sub(m: re.Match) -> str:
        val = get_var(m.group(1))
        return val if val is not None else m.group(0)

    return re.sub(r"\{\{vars\.([^}]+)\}\}", _sub, text)
