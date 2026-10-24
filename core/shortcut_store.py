"""Voice/text command shortcuts: keyword → pipeline message mappings."""
from __future__ import annotations

import json
import pathlib
import time
from typing import Optional


def _path() -> pathlib.Path:
    from core.config import get_config
    return pathlib.Path(get_config().memory_dir).expanduser() / "shortcuts.json"


def _load() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2))


def list_shortcuts() -> list[dict]:
    return _load()


def add_shortcut(keyword: str, message: str) -> int:
    items = _load()
    new_id = max((i["id"] for i in items), default=0) + 1
    items.append({"id": new_id, "keyword": keyword.lower().strip(), "message": message, "created_at": time.time()})
    _save(items)
    return new_id


def delete_shortcut(shortcut_id: int) -> bool:
    items = _load()
    new = [i for i in items if i["id"] != shortcut_id]
    if len(new) == len(items):
        return False
    _save(new)
    return True


def match_shortcut(text: str) -> Optional[str]:
    """Return mapped message if text matches a keyword (substring, case-insensitive), else None."""
    lower = text.lower().strip()
    for item in _load():
        if item["keyword"] in lower:
            return item["message"]
    return None
