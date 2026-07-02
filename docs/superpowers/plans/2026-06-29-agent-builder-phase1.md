# Agent Builder Phase 1 — Prompt Specialists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create custom specialist agents (name, system prompt, tool subset, trigger keywords) from the dashboard without editing Python or restarting the server.

**Architecture:** New `core/agent_store.py` stores agent definitions as JSON. A single `custom_agent_node` in `agents/custom_agent.py` joins the LangGraph graph at startup. `core/supervisor.py` gets three new in-memory dicts for custom routing, rebuilt synchronously by API endpoints after any mutation. Dashboard gets 6 REST endpoints and a new UI panel.

**Tech Stack:** FastAPI, LangGraph, Python dataclasses, JSON file store (`~/.plia/custom_agents.json`), existing `core/events.py` event bus.

## Global Constraints

- No new dependencies — uses only `core/events.py`, `agents/llm.py`, `core/registry.py`
- Agent `name` slug: lowercase alphanumeric + hyphens only, regex `^[a-z0-9-]+$`; immutable after creation
- Routing prefix `"custom:<name>"` distinguishes custom intents from built-in ones in supervisor state
- Disabled agents excluded from keyword routes and LLM classify prompt at reload time
- `tool_names` unknown to the live registry are silently skipped at execution time (not validated on save)
- All mutating API endpoints call `_reload_custom_agents()` then emit `agents_updated` event
- Tests use `AsyncClient(transport=ASGITransport(app=create_app()))` and patch `core.agent_store._AGENTS_FILE` to `tmp_path / "custom_agents.json"` for isolation
- Mock LLM in node/routing tests via `unittest.mock.patch("agents.llm.call_llm", new_callable=AsyncMock)`
- New server.py endpoints go before line 4907 (`@router.websocket("/ws")`)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `core/agent_store.py` | **Create** | `AgentDef` dataclass + JSON CRUD |
| `agents/custom_agent.py` | **Create** | LangGraph node dispatching all custom agents |
| `core/supervisor.py` | **Modify** | Custom routing dicts, `_reload_custom_agents()`, graph wiring |
| `dashboard/server.py` | **Modify** | 6 REST endpoints for agent CRUD |
| `dashboard/static/index.html` | **Modify** | Custom Agents panel: list + form |
| `tests/test_agent_store.py` | **Create** | Pure unit tests for store CRUD |
| `tests/test_custom_agent_node.py` | **Create** | Node unit tests with mock LLM |
| `tests/test_custom_agent_routing.py` | **Create** | API + routing integration tests |

---

## Task 1: Agent Store

**Files:**
- Create: `core/agent_store.py`
- Test: `tests/test_agent_store.py`

**Interfaces:**
- Produces:
  - `class AgentDef` — dataclass with fields: `name: str`, `display_name: str`, `system_prompt: str`, `tool_names: list[str]`, `keywords: list[str]`, `llm_description: str`, `enabled: bool = True`, `created_at: str = ""`
  - `list_agents() -> list[AgentDef]` — sorted by name
  - `get_agent(name: str) -> AgentDef | None`
  - `save_agent(defn: AgentDef) -> None` — create or overwrite; sets `created_at` on first save
  - `delete_agent(name: str) -> bool` — returns False if not found
  - `_AGENTS_FILE: Path` — module-level constant, patchable in tests

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_store.py
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch
from core.agent_store import AgentDef, list_agents, get_agent, save_agent, delete_agent


def _defn(**kwargs) -> AgentDef:
    defaults = dict(
        name="finance",
        display_name="Finance",
        system_prompt="You are a finance bot.",
        tool_names=["calculate"],
        keywords=["stock", "portfolio"],
        llm_description="Use for financial questions",
    )
    defaults.update(kwargs)
    return AgentDef(**defaults)


@pytest.fixture()
def store(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield


def test_get_unknown_returns_none(store):
    assert get_agent("nope") is None


def test_save_and_get_round_trip(store):
    d = _defn()
    save_agent(d)
    result = get_agent("finance")
    assert result is not None
    assert result.name == "finance"
    assert result.display_name == "Finance"
    assert result.system_prompt == "You are a finance bot."
    assert result.tool_names == ["calculate"]
    assert result.keywords == ["stock", "portfolio"]
    assert result.llm_description == "Use for financial questions"
    assert result.enabled is True


def test_save_sets_created_at(store):
    save_agent(_defn())
    result = get_agent("finance")
    assert result.created_at != ""


def test_update_preserves_created_at(store):
    save_agent(_defn())
    first_ts = get_agent("finance").created_at
    updated = _defn(display_name="Finance Updated")
    save_agent(updated)
    assert get_agent("finance").created_at == first_ts
    assert get_agent("finance").display_name == "Finance Updated"


def test_list_agents_sorted(store):
    save_agent(_defn(name="zebra", display_name="Z"))
    save_agent(_defn(name="alpha", display_name="A"))
    names = [a.name for a in list_agents()]
    assert names == ["alpha", "zebra"]


def test_delete_returns_true(store):
    save_agent(_defn())
    assert delete_agent("finance") is True
    assert get_agent("finance") is None


def test_delete_missing_returns_false(store):
    assert delete_agent("nope") is False


def test_invalid_slug_raises(store):
    with pytest.raises(ValueError, match="invalid"):
        save_agent(_defn(name="Bad Name!"))


def test_list_empty(store):
    assert list_agents() == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_agent_store.py -x -q
```
Expected: `ModuleNotFoundError: No module named 'core.agent_store'`

- [ ] **Step 3: Implement `core/agent_store.py`**

```python
from __future__ import annotations
import dataclasses
import json
import os
import re
from dataclasses import dataclass, field
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_agent_store.py -q
```
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add core/agent_store.py tests/test_agent_store.py
git commit -m "feat(agent-builder): add agent store with CRUD and slug validation"
```

---

## Task 2: Custom Agent Node

**Files:**
- Create: `agents/custom_agent.py`
- Test: `tests/test_custom_agent_node.py`

**Interfaces:**
- Consumes:
  - `get_agent(name: str) -> AgentDef | None` from `core/agent_store.py`
  - `get_tool_schemas() -> list[dict]` from `core/registry.py`
  - `call_llm(messages, tools) -> dict` from `agents/llm.py`
  - `AgentState` TypedDict from `core/supervisor.py` — fields used: `active_agent: str`, `messages: list[dict]`
- Produces:
  - `async def custom_agent_node(state: AgentState) -> dict` — returns `{"tool_results": [str]}`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_custom_agent_node.py
from __future__ import annotations
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from core.agent_store import AgentDef


def _state(active_agent: str, messages=None) -> dict:
    return {
        "active_agent": active_agent,
        "messages": messages or [{"role": "user", "content": "what is AAPL stock"}],
        "memory_context": "",
        "search_provider": "ddg",
        "hop_count": 1,
        "tool_results": [],
        "direct_result": "",
    }


def _defn(**kwargs) -> AgentDef:
    defaults = dict(
        name="finance",
        display_name="Finance",
        system_prompt="You are a finance specialist.",
        tool_names=["calculate"],
        keywords=["stock"],
        llm_description="Use for finance",
        enabled=True,
        created_at="",
    )
    defaults.update(kwargs)
    return AgentDef(**defaults)


@pytest.fixture()
def mock_store(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield


@pytest.mark.asyncio
async def test_node_uses_system_prompt(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn())
    mock_llm = AsyncMock(return_value={"content": "AAPL is $200"})
    with patch("agents.llm.call_llm", mock_llm):
        await custom_agent_node(_state("custom:finance"))
    call_messages = mock_llm.call_args[0][0]
    assert call_messages[0]["role"] == "system"
    assert call_messages[0]["content"] == "You are a finance specialist."


@pytest.mark.asyncio
async def test_node_filters_tools(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(tool_names=["calculate"]))
    mock_llm = AsyncMock(return_value={"content": "result"})
    fake_tools = [
        {"type": "function", "function": {"name": "calculate", "description": ""}},
        {"type": "function", "function": {"name": "web_search", "description": ""}},
    ]
    with patch("agents.llm.call_llm", mock_llm), \
         patch("core.registry.get_tool_schemas", return_value=fake_tools):
        await custom_agent_node(_state("custom:finance"))
    _, kwargs = mock_llm.call_args
    passed_tools = kwargs.get("tools") or mock_llm.call_args[0][1] if len(mock_llm.call_args[0]) > 1 else []
    assert len(passed_tools) == 1
    assert passed_tools[0]["function"]["name"] == "calculate"


@pytest.mark.asyncio
async def test_node_returns_content_in_tool_results(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn())
    with patch("agents.llm.call_llm", AsyncMock(return_value={"content": "AAPL is $200"})):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == ["AAPL is $200"]


@pytest.mark.asyncio
async def test_node_missing_agent_returns_error(mock_store):
    from agents.custom_agent import custom_agent_node
    result = await custom_agent_node(_state("custom:nonexistent"))
    assert len(result["tool_results"]) == 1
    assert "not found" in result["tool_results"][0]


@pytest.mark.asyncio
async def test_node_empty_tool_names_calls_llm_no_tools(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(tool_names=[]))
    mock_llm = AsyncMock(return_value={"content": "ok"})
    with patch("agents.llm.call_llm", mock_llm):
        result = await custom_agent_node(_state("custom:finance"))
    assert result["tool_results"] == ["ok"]
    _, kwargs = mock_llm.call_args
    tools_arg = kwargs.get("tools")
    assert tools_arg is None


@pytest.mark.asyncio
async def test_node_disabled_agent_returns_error(mock_store):
    from core.agent_store import save_agent
    from agents.custom_agent import custom_agent_node
    save_agent(_defn(enabled=False))
    result = await custom_agent_node(_state("custom:finance"))
    assert "not found or disabled" in result["tool_results"][0]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_custom_agent_node.py -x -q
```
Expected: `ModuleNotFoundError: No module named 'agents.custom_agent'`

- [ ] **Step 3: Implement `agents/custom_agent.py`**

```python
from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from core.agent_store import get_agent
from core.registry import get_tool_schemas

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)


async def custom_agent_node(state: "AgentState") -> dict:
    name = state["active_agent"].removeprefix("custom:")
    defn = await asyncio.to_thread(get_agent, name)
    if not defn or not defn.enabled:
        return {"tool_results": [f"Custom agent '{name}' not found or disabled"]}

    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    all_tools = get_tool_schemas()
    tools = [t for t in all_tools if t["function"]["name"] in defn.tool_names]
    msg = await call_llm(messages, tools=tools or None)
    return {"tool_results": [msg.get("content") or ""]}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_custom_agent_node.py -q
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/custom_agent.py tests/test_custom_agent_node.py
git commit -m "feat(agent-builder): add custom_agent_node dispatching all custom specialists"
```

---

## Task 3: Supervisor Wiring

**Files:**
- Modify: `core/supervisor.py`

**Interfaces:**
- Consumes:
  - `custom_agent_node` from `agents/custom_agent.py`
  - `list_agents() -> list[AgentDef]` from `core/agent_store.py`
- Produces:
  - `_reload_custom_agents() -> None` — public function called by API endpoints after mutations
  - `_build_classify_system() -> str` — returns base classify prompt extended with custom agent descriptions
  - `_custom_intents: set[str]` — module-level, used by routing tests to verify state

**Context on current `core/supervisor.py`:**
- `_CLASSIFY_SYSTEM` is a module-level string constant at ~line 33 — rename to `_CLASSIFY_SYSTEM_BASE`
- `_keyword_route()` is at ~line 158 — extend to check `_custom_keyword_routes`
- `_supervisor_node()` at ~line 184 uses `_CLASSIFY_SYSTEM` directly — change to `_build_classify_system()`
- `_route()` at ~line 318: `return state.get("active_agent") or "respond"` — add custom prefix check
- `_build_graph()` at ~line 322 — add `custom_agent_node` node and `"custom_agent"` edge
- `_graph = _build_graph()` at ~line 358 — reload custom agents after graph built

- [ ] **Step 1: Add module-level dicts and `_reload_custom_agents()` — no tests yet**

In `core/supervisor.py`, after the existing `_CACHE_STATS` line (~line 27), add:

```python
_custom_intents: set[str] = set()
_custom_keyword_routes: dict[str, list[str]] = {}
_custom_llm_descriptions: dict[str, str] = {}


def _reload_custom_agents() -> None:
    from core.agent_store import list_agents
    _custom_intents.clear()
    _custom_keyword_routes.clear()
    _custom_llm_descriptions.clear()
    for a in list_agents():
        if not a.enabled:
            continue
        intent = f"custom:{a.name}"
        _custom_intents.add(intent)
        if a.keywords:
            _custom_keyword_routes[intent] = [kw.lower() for kw in a.keywords]
        if a.llm_description:
            _custom_llm_descriptions[intent] = a.llm_description
```

- [ ] **Step 2: Rename `_CLASSIFY_SYSTEM` → `_CLASSIFY_SYSTEM_BASE` and add `_build_classify_system()`**

Find the existing constant (starts `"You are a router. Given the conversation..."`). Rename it:

```python
_CLASSIFY_SYSTEM_BASE = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder, network, wifi, file, weather, cron. "
    "Use 'reminder' for one-shot announcements at a specific future time ('remind me at 3pm', 'notify me in 2 hours'). "
    "Use 'cron' for recurring schedules ('every day at 8am', 'every weekday', 'every 30 minutes', cron job management). "
    "Use 'home' only for Home Assistant device control (lights, switches, sensors). "
    "Use 'network' for MAC address operations (show, change, randomize, spoof, restore MAC address). "
    "Use 'wifi' for WiFi status, scanning nearby networks, or listing WiFi interfaces. "
    "Use 'file' for reading, writing, finding, searching, or running files and directories; also PDF, Word, Excel, PowerPoint documents. "
    "Use 'weather' for weather conditions, forecasts, temperature, rain, UV index, or climate queries. "
    "Use 'respond' for countdown timers, volume, system info, calculations, or anything answerable with tools directly."
)


def _build_classify_system() -> str:
    if not _custom_llm_descriptions:
        return _CLASSIFY_SYSTEM_BASE
    extras = "\n".join(
        f"Use '{intent}' for: {desc}"
        for intent, desc in _custom_llm_descriptions.items()
    )
    return _CLASSIFY_SYSTEM_BASE + f"\nCustom specialists:\n{extras}"
```

- [ ] **Step 3: Update `_supervisor_node` to use `_build_classify_system()` and check `_custom_intents`**

In `_supervisor_node`, find the classify block (~line 231):

```python
# OLD:
classify_messages = [
    {"role": "system", "content": _CLASSIFY_SYSTEM},
    *state["messages"],
]
```

```python
# NEW:
classify_messages = [
    {"role": "system", "content": _build_classify_system()},
    *state["messages"],
]
```

Also update the intent validation after the LLM call (~line 241):

```python
# OLD:
if intent not in _KNOWN_INTENTS:
    intent = "respond"

# NEW:
if intent not in _KNOWN_INTENTS and intent not in _custom_intents:
    intent = "respond"
```

- [ ] **Step 4: Extend `_keyword_route()` to check custom routes**

Find `_keyword_route()` (~line 158) and replace with:

```python
def _keyword_route(text: str) -> str | None:
    lower = text.lower()
    for intent, keywords in _KEYWORD_ROUTES.items():
        if any(kw in lower for kw in keywords):
            return intent
    for intent, keywords in _custom_keyword_routes.items():
        if any(kw in lower for kw in keywords):
            return intent
    return None
```

- [ ] **Step 5: Update `_route()` to handle custom prefix**

Find `_route()` (~line 318):

```python
# OLD:
def _route(state: AgentState) -> str:
    return state.get("active_agent") or "respond"

# NEW:
def _route(state: AgentState) -> str:
    intent = state.get("active_agent") or "respond"
    if intent.startswith("custom:"):
        return "custom_agent"
    return intent
```

- [ ] **Step 6: Wire `custom_agent_node` into `_build_graph()` and reload on startup**

In `_build_graph()` (~line 322), add after the existing node registrations:

```python
from agents.custom_agent import custom_agent_node
g.add_node("custom_agent", custom_agent_node)
g.add_edge("custom_agent", "supervisor")
```

And add `"custom_agent": "custom_agent"` to the `add_conditional_edges` dict:

```python
g.add_conditional_edges("supervisor", _route, {
    "memory": "memory",
    "web": "web",
    "code": "code",
    "calendar": "calendar",
    "home": "home",
    "reminder": "reminder",
    "network": "network",
    "wifi": "wifi",
    "file": "file",
    "weather": "weather",
    "cron": "respond",
    "respond": "respond",
    "custom_agent": "custom_agent",
})
```

After the `_graph = _build_graph()` line (~line 358), add:

```python
_reload_custom_agents()
```

- [ ] **Step 7: Verify existing tests still pass**

```bash
pytest --tb=short -q -x
```
Expected: same pass count as before (2 pre-existing failures unrelated to this change)

- [ ] **Step 8: Commit**

```bash
git add core/supervisor.py
git commit -m "feat(agent-builder): wire custom_agent_node into supervisor routing"
```

---

## Task 4: API Endpoints

**Files:**
- Modify: `dashboard/server.py` (add 6 endpoints before line 4907)
- Test: `tests/test_custom_agent_routing.py`

**Interfaces:**
- Consumes:
  - `AgentDef`, `list_agents`, `get_agent`, `save_agent`, `delete_agent` from `core/agent_store.py`
  - `_reload_custom_agents` from `core/supervisor.py`
  - `events.emit` from `core/events.py`
- Produces:
  - `GET /api/agents` → `{"agents": [{"name", "display_name", "enabled", "keyword_count", "tool_count"}]}`
  - `POST /api/agents` → `201` + full AgentDef as dict; `409` name exists; `422` invalid slug
  - `GET /api/agents/{name}` → full AgentDef as dict; `404` if missing
  - `PUT /api/agents/{name}` → `200` + updated AgentDef; `404` if missing
  - `DELETE /api/agents/{name}` → `200 {"ok": true}`; `404` if missing
  - `POST /api/agents/{name}/toggle` → `200 {"name": str, "enabled": bool}`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_custom_agent_routing.py
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_DEFN = {
    "name": "finance",
    "display_name": "Finance Assistant",
    "system_prompt": "You are a finance specialist.",
    "tool_names": ["calculate"],
    "keywords": ["stock", "portfolio"],
    "llm_description": "Use for financial questions",
    "enabled": True,
}


@pytest.fixture()
def agents_file(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield tmp_path / "custom_agents.json"


@pytest.mark.asyncio
async def test_list_empty(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/agents")
    assert r.status_code == 200
    assert r.json()["agents"] == []


@pytest.mark.asyncio
async def test_create_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json=_DEFN)
    assert r.status_code == 201
    d = r.json()
    assert d["name"] == "finance"
    assert d["display_name"] == "Finance Assistant"
    assert d["created_at"] != ""


@pytest.mark.asyncio
async def test_create_duplicate_409(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.post("/api/agents", json=_DEFN)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_invalid_slug_422(agents_file):
    bad = {**_DEFN, "name": "Bad Name!"}
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/agents", json=bad)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.get("/api/agents/finance")
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "You are a finance specialist."


@pytest.mark.asyncio
async def test_get_missing_404(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/agents/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.put("/api/agents/finance", json={"display_name": "Finance v2",
                                                      "system_prompt": "Updated.",
                                                      "tool_names": [],
                                                      "keywords": [],
                                                      "llm_description": "",
                                                      "enabled": True})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Finance v2"


@pytest.mark.asyncio
async def test_update_missing_404(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.put("/api/agents/nope", json={"display_name": "x", "system_prompt": "x",
                                                   "tool_names": [], "keywords": [],
                                                   "llm_description": "", "enabled": True})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.delete("/api/agents/finance")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_missing_404(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/agents/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_toggle_agent(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.post("/api/agents/finance/toggle")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "finance"
    assert d["enabled"] is False


@pytest.mark.asyncio
async def test_list_shows_counts(agents_file):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        r = await c.get("/api/agents")
    agents = r.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["keyword_count"] == 2
    assert agents[0]["tool_count"] == 1


@pytest.mark.asyncio
async def test_agents_updated_event_fires_on_create(agents_file):
    from core import events
    fired = []
    async def capture(p):
        if p.get("type") == "agents_updated":
            fired.append(p)
    events.subscribe(capture)
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/agents", json=_DEFN)
    finally:
        events.unsubscribe(capture)
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_agents_updated_event_fires_on_delete(agents_file):
    from core import events
    fired = []
    async def capture(p):
        if p.get("type") == "agents_updated":
            fired.append(p)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/agents", json=_DEFN)
        events.subscribe(capture)
        try:
            await c.delete("/api/agents/finance")
        finally:
            events.unsubscribe(capture)
    assert len(fired) == 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_custom_agent_routing.py -x -q
```
Expected: `404 Not Found` (endpoints don't exist yet)

- [ ] **Step 3: Add 6 endpoints to `dashboard/server.py` before `@router.websocket("/ws")` (line 4907)**

```python
# ── Custom agent builder ───────────────────────────────────────────────────────

import dataclasses as _agent_dc

@router.get("/api/agents")
async def list_custom_agents():
    from core.agent_store import list_agents
    agents = await asyncio.to_thread(list_agents)
    return {
        "agents": [
            {
                "name": a.name,
                "display_name": a.display_name,
                "enabled": a.enabled,
                "keyword_count": len(a.keywords),
                "tool_count": len(a.tool_names),
            }
            for a in agents
        ]
    }


@router.post("/api/agents", status_code=201)
async def create_custom_agent(body: dict):
    from core.agent_store import AgentDef, get_agent, save_agent
    from core.supervisor import _reload_custom_agents
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name required")
    existing = await asyncio.to_thread(get_agent, name)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Agent '{name}' already exists")
    try:
        defn = AgentDef(
            name=name,
            display_name=(body.get("display_name") or "").strip(),
            system_prompt=(body.get("system_prompt") or "").strip(),
            tool_names=list(body.get("tool_names") or []),
            keywords=list(body.get("keywords") or []),
            llm_description=(body.get("llm_description") or "").strip(),
            enabled=bool(body.get("enabled", True)),
        )
        await asyncio.to_thread(save_agent, defn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _reload_custom_agents()
    await events.emit("agents_updated", {"action": "create", "name": name})
    return _agent_dc.asdict(await asyncio.to_thread(get_agent, name))


@router.get("/api/agents/{name}")
async def get_custom_agent(name: str):
    from core.agent_store import get_agent
    defn = await asyncio.to_thread(get_agent, name)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    import dataclasses as _dc
    return _dc.asdict(defn)


@router.put("/api/agents/{name}")
async def update_custom_agent(name: str, body: dict):
    from core.agent_store import AgentDef, get_agent, save_agent
    from core.supervisor import _reload_custom_agents
    existing = await asyncio.to_thread(get_agent, name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    updated = AgentDef(
        name=name,
        display_name=(body.get("display_name") or "").strip(),
        system_prompt=(body.get("system_prompt") or "").strip(),
        tool_names=list(body.get("tool_names") or []),
        keywords=list(body.get("keywords") or []),
        llm_description=(body.get("llm_description") or "").strip(),
        enabled=bool(body.get("enabled", True)),
        created_at=existing.created_at,
    )
    await asyncio.to_thread(save_agent, updated)
    _reload_custom_agents()
    await events.emit("agents_updated", {"action": "update", "name": name})
    import dataclasses as _dc
    return _dc.asdict(await asyncio.to_thread(get_agent, name))


@router.delete("/api/agents/{name}")
async def delete_custom_agent(name: str):
    from core.agent_store import delete_agent
    from core.supervisor import _reload_custom_agents
    ok = await asyncio.to_thread(delete_agent, name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    _reload_custom_agents()
    await events.emit("agents_updated", {"action": "delete", "name": name})
    return {"ok": True}


@router.post("/api/agents/{name}/toggle")
async def toggle_custom_agent(name: str):
    from core.agent_store import get_agent, save_agent
    from core.supervisor import _reload_custom_agents
    defn = await asyncio.to_thread(get_agent, name)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    defn.enabled = not defn.enabled
    await asyncio.to_thread(save_agent, defn)
    _reload_custom_agents()
    await events.emit("agents_updated", {"action": "toggle", "name": name})
    return {"name": name, "enabled": defn.enabled}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_custom_agent_routing.py -q
```
Expected: `15 passed`

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
pytest --tb=short -q
```
Expected: same pass count as before (only the 2 pre-existing failures)

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_custom_agent_routing.py
git commit -m "feat(agent-builder): add CRUD REST endpoints and agents_updated event"
```

---

## Task 5: Dashboard UI Panel

**Files:**
- Modify: `dashboard/static/index.html`

**No new tests** — UI is untested per project convention.

**Where to insert:** Nav button after last existing panel button. Panel div before `<!-- Wake Word Test -->`. JS functions before `// ── Tool playground ──`.

- [ ] **Step 1: Add nav button**

Find the nav section with existing panel buttons. After the last tool-related button, add:

```html
<button class="nav-btn" data-section="customagents" onclick="showSection('customagents')">Custom Agents</button>
```

- [ ] **Step 2: Add panel HTML before `<!-- Wake Word Test -->`**

```html
<!-- Custom Agents -->
<div id="section-customagents" class="section" style="display:none">
  <h2>Custom Agents</h2>
  <p style="color:#888;margin-bottom:1rem">Define specialist agents with custom system prompts, tool access, and trigger keywords. No restart needed.</p>

  <button onclick="caShowForm(null)" style="margin-bottom:1rem">+ New Agent</button>

  <div id="ca-list">Loading…</div>

  <div id="ca-form-wrap" style="display:none;margin-top:1.5rem;background:#1a1a2e;border:1px solid #333;border-radius:8px;padding:1.5rem">
    <h3 id="ca-form-title">New Agent</h3>
    <label>Name (slug, immutable after creation)</label>
    <input id="ca-name" placeholder="finance" style="width:100%;margin-bottom:.75rem" />
    <label>Display Name</label>
    <input id="ca-display-name" placeholder="Finance Assistant" style="width:100%;margin-bottom:.75rem" />
    <label>System Prompt</label>
    <textarea id="ca-system-prompt" rows="6" placeholder="You are a finance specialist..." style="width:100%;margin-bottom:.75rem"></textarea>
    <label>Keywords (comma-separated, fast trigger phrases)</label>
    <input id="ca-keywords" placeholder="stock, portfolio, finance" style="width:100%;margin-bottom:.75rem" />
    <label>LLM Description (one sentence — used by router when no keyword matches)</label>
    <input id="ca-llm-desc" placeholder="Use for stock prices and portfolio questions" style="width:100%;margin-bottom:.75rem" />
    <label>Tools</label>
    <div id="ca-tools-list" style="max-height:200px;overflow-y:auto;background:#111;border:1px solid #333;border-radius:4px;padding:.5rem;margin-bottom:.75rem">Loading tools…</div>
    <label style="display:flex;align-items:center;gap:.5rem;margin-bottom:1rem">
      <input type="checkbox" id="ca-enabled" checked /> Enabled
    </label>
    <div style="display:flex;gap:.75rem">
      <button onclick="caSave()">Save</button>
      <button onclick="caHideForm()" style="background:#333">Cancel</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add JS before `// ── Tool playground ──`**

```javascript
// ── Custom Agents ──────────────────────────────────────────────────────────
let _caEditName = null;
let _caAllTools = [];

async function caLoad() {
  const r = await fetch('/api/agents');
  const d = await r.json();
  const agents = d.agents;
  const el = document.getElementById('ca-list');
  if (!agents.length) { el.innerHTML = '<p style="color:#888">No custom agents yet.</p>'; return; }
  el.innerHTML = `<table style="width:100%;border-collapse:collapse">
    <thead><tr style="border-bottom:1px solid #333">
      <th style="text-align:left;padding:.4rem .6rem">Name</th>
      <th style="text-align:left;padding:.4rem .6rem">Keywords</th>
      <th style="text-align:left;padding:.4rem .6rem">Tools</th>
      <th style="padding:.4rem .6rem">Enabled</th>
      <th style="padding:.4rem .6rem">Actions</th>
    </tr></thead>
    <tbody>${agents.map(a => `
      <tr style="border-bottom:1px solid #222">
        <td style="padding:.4rem .6rem"><strong>${_esc(a.display_name)}</strong><br><small style="color:#888">${_esc(a.name)}</small></td>
        <td style="padding:.4rem .6rem">${a.keyword_count}</td>
        <td style="padding:.4rem .6rem">${a.tool_count}</td>
        <td style="text-align:center;padding:.4rem .6rem">
          <input type="checkbox" ${a.enabled ? 'checked' : ''} onchange="caToggle('${_esc(a.name)}')" />
        </td>
        <td style="text-align:center;padding:.4rem .6rem">
          <button onclick="caShowForm('${_esc(a.name)}')" style="padding:.2rem .6rem;font-size:.8rem">Edit</button>
          <button onclick="caDelete('${_esc(a.name)}')" style="padding:.2rem .6rem;font-size:.8rem;background:#7f1d1d;margin-left:.25rem">Delete</button>
        </td>
      </tr>`).join('')}
    </tbody></table>`;
}

async function caLoadTools() {
  if (_caAllTools.length) return;
  const r = await fetch('/api/tools');
  const d = await r.json();
  _caAllTools = d.tools || [];
}

async function caShowForm(name) {
  await caLoadTools();
  _caEditName = name;
  document.getElementById('ca-form-title').textContent = name ? 'Edit Agent' : 'New Agent';
  document.getElementById('ca-name').disabled = !!name;
  let defn = {name:'',display_name:'',system_prompt:'',keywords:[],llm_description:'',tool_names:[],enabled:true};
  if (name) {
    const r = await fetch(`/api/agents/${encodeURIComponent(name)}`);
    defn = await r.json();
  }
  document.getElementById('ca-name').value = defn.name || '';
  document.getElementById('ca-display-name').value = defn.display_name || '';
  document.getElementById('ca-system-prompt').value = defn.system_prompt || '';
  document.getElementById('ca-keywords').value = (defn.keywords || []).join(', ');
  document.getElementById('ca-llm-desc').value = defn.llm_description || '';
  document.getElementById('ca-enabled').checked = defn.enabled !== false;
  const toolsEl = document.getElementById('ca-tools-list');
  toolsEl.innerHTML = _caAllTools.map(t =>
    `<label style="display:flex;align-items:center;gap:.4rem;margin-bottom:.25rem">
      <input type="checkbox" value="${_esc(t.name)}" ${(defn.tool_names||[]).includes(t.name)?'checked':''} />
      <span>${_esc(t.name)}</span> <small style="color:#888">${_esc(t.description||'')}</small>
    </label>`
  ).join('');
  document.getElementById('ca-form-wrap').style.display = 'block';
}

function caHideForm() {
  document.getElementById('ca-form-wrap').style.display = 'none';
  _caEditName = null;
}

async function caSave() {
  const name = document.getElementById('ca-name').value.trim();
  const body = {
    name,
    display_name: document.getElementById('ca-display-name').value.trim(),
    system_prompt: document.getElementById('ca-system-prompt').value.trim(),
    keywords: document.getElementById('ca-keywords').value.split(',').map(s=>s.trim()).filter(Boolean),
    llm_description: document.getElementById('ca-llm-desc').value.trim(),
    tool_names: [...document.querySelectorAll('#ca-tools-list input:checked')].map(el=>el.value),
    enabled: document.getElementById('ca-enabled').checked,
  };
  const url = _caEditName ? `/api/agents/${encodeURIComponent(_caEditName)}` : '/api/agents';
  const method = _caEditName ? 'PUT' : 'POST';
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  if (!r.ok) { alert((await r.json()).detail || 'Save failed'); return; }
  caHideForm();
  await caLoad();
}

async function caToggle(name) {
  await fetch(`/api/agents/${encodeURIComponent(name)}/toggle`, {method:'POST'});
  await caLoad();
}

async function caDelete(name) {
  if (!confirm(`Delete agent '${name}'?`)) return;
  await fetch(`/api/agents/${encodeURIComponent(name)}`, {method:'DELETE'});
  await caLoad();
}

// load on section show
const _caOrigShowSection = typeof showSection === 'function' ? showSection : null;
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-section="customagents"]').forEach(btn => {
    btn.addEventListener('click', caLoad);
  });
});
```

- [ ] **Step 4: Manually verify**

```bash
source .venv/bin/activate && python core/main.py
```

Open `http://localhost:8000`. Click "Custom Agents" nav button. Verify:
- Panel loads with "No custom agents yet."
- "+ New Agent" opens form with tool checkboxes populated
- Create an agent → appears in list
- Toggle enabled → checkbox reflects new state
- Edit → form pre-populated with existing values
- Delete → confirmation dialog → agent removed
- After any mutation, re-click "Custom Agents" → list refreshes

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(agent-builder): add Custom Agents dashboard panel with list and form"
```

---

## Self-Review

**Spec coverage:**
- `core/agent_store.py` with `AgentDef`, CRUD, slug validation → Task 1 ✅
- `agents/custom_agent.py` with `custom_agent_node` → Task 2 ✅
- Supervisor: `_custom_intents`, `_custom_keyword_routes`, `_custom_llm_descriptions`, `_reload_custom_agents()`, `_build_classify_system()`, `_route()` update, graph wiring → Task 3 ✅
- 6 REST endpoints, `agents_updated` event → Task 4 ✅
- Dashboard panel → Task 5 ✅
- All 3 test files, 30 total tests → Tasks 1, 2, 4 ✅

**Placeholder scan:** None found. All steps contain complete code.

**Type consistency:** `AgentDef` defined in Task 1, used identically in Tasks 2, 3, 4. `_reload_custom_agents()` defined in Task 3, called in Task 4. `custom_agent_node` defined in Task 2, imported in Task 3. All function names match across tasks.

**One issue fixed inline:** Task 4 `update_custom_agent` preserves `created_at` from existing record before calling `save_agent`, preventing the store from overwriting it with a new timestamp on update.
