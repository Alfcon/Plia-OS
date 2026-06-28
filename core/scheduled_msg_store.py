from __future__ import annotations

import json
import time
from pathlib import Path


def _path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / "scheduled_messages.json"


def _load() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _save(msgs: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(msgs, indent=2))


def add_scheduled_message(message: str, fire_at_iso: str) -> int:
    msgs = _load()
    new_id = max((m["id"] for m in msgs), default=0) + 1
    msgs.append({
        "id": new_id,
        "message": message,
        "fire_at": fire_at_iso,
        "created_at": int(time.time()),
        "done": False,
    })
    _save(msgs)
    return new_id


def list_scheduled_messages(include_done: bool = False) -> list[dict]:
    msgs = _load()
    if not include_done:
        msgs = [m for m in msgs if not m.get("done")]
    return sorted(msgs, key=lambda m: m["fire_at"])


def get_pending_scheduled() -> list[dict]:
    """Return messages whose fire_at <= now and not done."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return [m for m in _load() if not m.get("done") and m["fire_at"] <= now]


def mark_scheduled_done(msg_id: int) -> bool:
    msgs = _load()
    for m in msgs:
        if m["id"] == msg_id:
            m["done"] = True
            _save(msgs)
            return True
    return False


def delete_scheduled_message(msg_id: int) -> bool:
    msgs = _load()
    new = [m for m in msgs if m["id"] != msg_id]
    if len(new) == len(msgs):
        return False
    _save(new)
    return True
