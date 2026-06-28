from __future__ import annotations

import dataclasses
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


_INTERNAL_FIELDS = {"system_prompt_backup"}


def _snapshots_dir() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / "snapshots"


def _safe_label(label: str) -> str:
    label = label.strip()[:40]
    label = re.sub(r"[^\w\-]", "_", label)
    return label


def _snap_path(name: str) -> Path:
    safe = Path(name).name
    if not safe or safe in (".", ".."):
        raise ValueError("Invalid snapshot name")
    return _snapshots_dir() / safe


def list_snapshots() -> list[dict]:
    d = _snapshots_dir()
    if not d.exists():
        return []
    snaps = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            snaps.append({
                "name": p.name,
                "label": data.get("_label", ""),
                "created_at": data.get("_created_at", 0),
                "size": p.stat().st_size,
            })
        except Exception:
            pass
    snaps.sort(key=lambda s: s["created_at"], reverse=True)
    return snaps


def get_snapshot(name: str) -> dict | None:
    try:
        p = _snap_path(name)
    except ValueError:
        return None
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def create_snapshot(label: str = "") -> str:
    from core.config import get_config
    d = _snapshots_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = _safe_label(label)
    name = f"{ts}_{safe}.json" if safe else f"{ts}.json"
    data = dataclasses.asdict(get_config())
    data["_label"] = label
    data["_created_at"] = int(time.time())
    (d / name).write_text(json.dumps(data, indent=2))
    return name


def restore_snapshot(name: str) -> dict:
    from core.config import update_config
    snap = get_snapshot(name)
    if snap is None:
        raise KeyError(f"Snapshot {name!r} not found")
    # Auto-save pre-restore backup
    create_snapshot(label="pre-restore")
    kwargs = {
        k: v for k, v in snap.items()
        if not k.startswith("_") and k not in _INTERNAL_FIELDS
    }
    update_config(**kwargs)
    return {"restored": name, "fields": len(kwargs)}


def delete_snapshot(name: str) -> bool:
    try:
        p = _snap_path(name)
    except ValueError:
        return False
    if not p.exists():
        return False
    p.unlink()
    return True
