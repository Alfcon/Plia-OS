from __future__ import annotations
import dataclasses
import json
import os
from pathlib import Path

from core.config import PliaConfig, get_config, update_config

_PRESETS_FILE = Path(
    os.environ.get("PLIA_PRESETS_FILE", str(Path.home() / ".plia" / "config_presets.json"))
)


def _load() -> dict:
    try:
        return json.loads(_PRESETS_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    _PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PRESETS_FILE.write_text(json.dumps(data, indent=2))


def list_presets() -> list[str]:
    return sorted(_load().keys())


def save_preset(name: str) -> None:
    cfg = get_config()
    data = _load()
    data[name] = dataclasses.asdict(cfg)
    _save(data)


def apply_preset(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    preset = data[name]
    known = {f.name for f in dataclasses.fields(PliaConfig)}
    kwargs = {k: v for k, v in preset.items() if k in known}
    update_config(**kwargs)
    return True


def delete_preset(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True
