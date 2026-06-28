from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def _forks_dir() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / "forks"


def _safe_name(label: str) -> str:
    label = label.strip()[:40]
    return re.sub(r"[^\w\-]", "_", label) if label else ""


def _fork_path(name: str) -> Path:
    safe = Path(name).name
    if not safe or safe in (".", ".."):
        raise ValueError(f"Invalid fork name: {name!r}")
    return _forks_dir() / safe


def list_forks() -> list[dict]:
    d = _forks_dir()
    if not d.exists():
        return []
    forks = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            forks.append({
                "name": p.name,
                "label": data.get("_label", ""),
                "created_at": data.get("_created_at", 0),
                "turn_count": len(data.get("turns", [])),
            })
        except Exception:
            pass
    forks.sort(key=lambda f: f["created_at"], reverse=True)
    return forks


def save_fork(label: str, turns: list[dict]) -> str:
    d = _forks_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = _safe_name(label)
    name = f"{ts}_{safe}.json" if safe else f"{ts}.json"
    data = {"_label": label, "_created_at": int(time.time()), "turns": turns}
    (d / name).write_text(json.dumps(data, indent=2))
    return name


def get_fork(name: str) -> dict | None:
    try:
        p = _fork_path(name)
    except ValueError:
        return None
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def delete_fork(name: str) -> bool:
    try:
        p = _fork_path(name)
    except ValueError:
        return False
    if not p.exists():
        return False
    p.unlink()
    return True
