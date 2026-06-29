from __future__ import annotations
import dataclasses
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_AGENTS_FILE = Path(
    os.environ.get("PLIA_AGENTS_FILE",
                   str(Path(os.environ.get("PLIA_CONFIG_FILE",
                                           str(Path.home() / ".plia" / "config.json"))).parent
                       / "custom_agents.json"))
)

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


@dataclass
class AgentDef:
    name: str
    display_name: str
    system_prompt: str
    tool_names: list[str]
    keywords: list[str]
    llm_description: str
    enabled: bool = True
    created_at: str = ""


def _load() -> dict:
    try:
        return json.loads(_AGENTS_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    _AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AGENTS_FILE.write_text(json.dumps(data, indent=2))


def list_agents() -> list[AgentDef]:
    return sorted(
        (_from_dict(v) for v in _load().values()),
        key=lambda a: a.name,
    )


def get_agent(name: str) -> AgentDef | None:
    data = _load()
    return _from_dict(data[name]) if name in data else None


def save_agent(defn: AgentDef) -> None:
    if not _SLUG_RE.match(defn.name):
        raise ValueError(f"Agent name {defn.name!r} is invalid — use lowercase letters, digits, hyphens only")
    data = _load()
    existing = data.get(defn.name)
    d = dataclasses.asdict(defn)
    if existing:
        d["created_at"] = existing.get("created_at", defn.created_at)
    else:
        d["created_at"] = datetime.now(timezone.utc).isoformat()
    data[defn.name] = d
    _save(data)


def delete_agent(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True


def _from_dict(d: dict) -> AgentDef:
    return AgentDef(
        name=d["name"],
        display_name=d.get("display_name", ""),
        system_prompt=d.get("system_prompt", ""),
        tool_names=d.get("tool_names", []),
        keywords=d.get("keywords", []),
        llm_description=d.get("llm_description", ""),
        enabled=bool(d.get("enabled", True)),
        created_at=d.get("created_at", ""),
    )
