# Agent Builder — Phase 1: Prompt Specialists

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users define custom specialist agents — name, system prompt, tool subset, trigger keywords — from the dashboard, without editing Python or restarting the server.

**Phase:** 1 of 2. Phase 2 (workflow agents with step sequences and event/schedule triggers) is a separate spec.

**Architecture:** Single `custom_agent_node` joins the LangGraph graph at startup and handles all custom agents via dispatch. Custom agent definitions stored in `~/.plia/custom_agents.json`. Supervisor routing updated in-memory on `agents_updated` event — no restart needed.

**Tech Stack:** FastAPI, LangGraph, Python dataclasses, JSON file store, asyncio event bus.

---

## Global Constraints

- No new dependencies — uses existing `core/events.py`, `agents/llm.py`, `core/registry.py`
- Custom agents stored in `~/.plia/custom_agents.json` (respects `PLIA_CONFIG_FILE` dir convention)
- Agent `name` is a slug: lowercase, alphanumeric + hyphens, unique, immutable after creation
- Routing prefix `"custom:<name>"` distinguishes custom intents from built-in ones
- Disabled agents are ignored at routing time — keywords and LLM description excluded
- `tool_names` must contain only names present in the live tool registry; unknown names are silently skipped at execution time (registry may change between restarts)
- All mutating API endpoints emit `agents_updated` after writing
- Tests use `AsyncClient(transport=ASGITransport(app=create_app()))` per project convention
- Mock LLM in tests via `unittest.mock.patch("agents.llm.call_llm")`

---

## Data Model

```python
# core/agent_store.py
@dataclass
class AgentDef:
    name: str           # slug — routing key, e.g. "finance"
    display_name: str   # UI label, e.g. "Finance Assistant"
    system_prompt: str  # injected as first system message when node runs
    tool_names: list[str]       # subset of registered tool names
    keywords: list[str]         # fast-path trigger phrases (lowercased at match time)
    llm_description: str        # one sentence appended to classifier system prompt
    enabled: bool = True
    created_at: str = ""        # ISO 8601, set on first save
```

Stored as a JSON dict keyed by `name`:

```json
{
  "finance": {
    "name": "finance",
    "display_name": "Finance Assistant",
    "system_prompt": "You are a finance specialist...",
    "tool_names": ["calculate", "web_search"],
    "keywords": ["stock", "portfolio", "finance"],
    "llm_description": "Use for stock prices, portfolio questions, financial analysis",
    "enabled": true,
    "created_at": "2026-06-29T10:00:00Z"
  }
}
```

Storage path: `Path(os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))).parent / "custom_agents.json"`

---

## Components

### `core/agent_store.py` (new)

CRUD over `custom_agents.json`. All functions synchronous — callers use `asyncio.to_thread()`.

```python
def list_agents() -> list[AgentDef]: ...        # sorted by name
def get_agent(name: str) -> AgentDef | None: ...
def save_agent(defn: AgentDef) -> None: ...     # create or overwrite
def delete_agent(name: str) -> bool: ...        # False if not found
```

Sets `created_at` on first save (not on update). Validates `name` matches `^[a-z0-9-]+$`.

### `agents/custom_agent.py` (new)

Single LangGraph node handling all custom agents:

```python
async def custom_agent_node(state: AgentState) -> dict:
    name = state["active_agent"].removeprefix("custom:")
    defn = await asyncio.to_thread(get_agent, name)
    if not defn or not defn.enabled:
        return {"tool_results": [f"Custom agent '{name}' not found or disabled"]}

    messages = [
        {"role": "system", "content": defn.system_prompt},
        *[m for m in state["messages"] if m["role"] != "system"],
    ]
    all_tools = get_tool_schemas()
    tools = [t for t in all_tools
             if t["function"]["name"] in defn.tool_names]
    msg = await call_llm(messages, tools=tools or None)
    return {"tool_results": [msg.get("content") or ""]}
```

### `core/supervisor.py` (modified)

**At module level** — two new mutable structures:

```python
_custom_intents: set[str] = set()          # "custom:finance", etc.
_custom_keyword_routes: dict[str, list[str]] = {}
_custom_llm_descriptions: dict[str, str] = {}
```

**`_reload_custom_agents()`** — called at startup and on `agents_updated`:

```python
def _reload_custom_agents() -> None:
    from core.agent_store import list_agents
    agents = list_agents()
    _custom_intents.clear()
    _custom_keyword_routes.clear()
    _custom_llm_descriptions.clear()
    for a in agents:
        if not a.enabled:
            continue
        intent = f"custom:{a.name}"
        _custom_intents.add(intent)
        if a.keywords:
            _custom_keyword_routes[intent] = a.keywords
        if a.llm_description:
            _custom_llm_descriptions[intent] = a.llm_description
```

**`_keyword_route()`** — extended to check custom routes after built-in:

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

**`_CLASSIFY_SYSTEM`** — built dynamically per call when custom agents exist:

```python
def _build_classify_system() -> str:
    base = _CLASSIFY_SYSTEM_BASE  # the existing constant
    if not _custom_llm_descriptions:
        return base
    extras = "\n".join(
        f"Use '{intent}' for: {desc}"
        for intent, desc in _custom_llm_descriptions.items()
    )
    return base + f"\nCustom specialists:\n{extras}"
```

**`_route()`** — one new branch:

```python
def _route(state: AgentState) -> str:
    intent = state["active_agent"]
    if intent and intent.startswith("custom:"):
        return "custom_agent"
    return intent or "respond"
```

**Graph construction** — `custom_agent_node` added as static node:

```python
from agents.custom_agent import custom_agent_node
g.add_node("custom_agent", custom_agent_node)
g.add_edge("custom_agent", "supervisor")
```

**Event subscription** — supervisor subscribes to `agents_updated` at graph build time:

```python
async def _on_agents_updated(payload: dict) -> None:
    _reload_custom_agents()

events.subscribe(_on_agents_updated)
_reload_custom_agents()  # load on startup
```

### `dashboard/server.py` (modified — 6 new endpoints)

```
GET    /api/agents              list all (id fields only — name, display_name, enabled, len(keywords), len(tool_names))
POST   /api/agents              create (validates name slug, 409 if exists)
GET    /api/agents/{name}       full definition
PUT    /api/agents/{name}       update (404 if not found)
DELETE /api/agents/{name}       delete (404 if not found)
POST   /api/agents/{name}/toggle  flip enabled, return new state
```

Each mutating endpoint: write → `await events.emit("agents_updated", {})`.

### `dashboard/static/index.html` (modified)

New **Custom Agents** panel. Nav button after existing tool buttons.

**List view:**
- Table: Display Name | Keywords | Tools | Enabled (toggle) | Edit | Delete
- "New Agent" button opens form

**Form (create / edit):**
- Display name — text input
- System prompt — textarea (6 rows)
- Keywords — comma-separated text input (split/join on save/load)
- LLM description — text input (one sentence)
- Tool picker — multi-select checklist populated from `GET /api/tools`
- Enabled — checkbox
- Name slug — text input (create only; shown read-only on edit)
- Save / Cancel buttons

On Save: `POST /api/agents` or `PUT /api/agents/{name}` → reload list.

---

## API Contracts

### `POST /api/agents`
```json
{
  "name": "finance",
  "display_name": "Finance Assistant",
  "system_prompt": "You are a finance specialist...",
  "tool_names": ["calculate"],
  "keywords": ["stock", "portfolio"],
  "llm_description": "Use for financial questions",
  "enabled": true
}
```
Returns `201` + full definition. `409` if name exists. `422` if name fails slug validation.

### `PUT /api/agents/{name}`
Same body as POST minus `name`. Returns `200` + updated definition. `404` if not found.

### `DELETE /api/agents/{name}`
Returns `200 {"ok": true}`. `404` if not found.

### `POST /api/agents/{name}/toggle`
Returns `200 {"name": "finance", "enabled": false}`.

---

## Testing

### `tests/test_agent_store.py` (pure unit)
- `save_agent` → `get_agent` round-trip returns identical definition
- `list_agents` returns all saved agents sorted by name
- `delete_agent` returns `True`; second call returns `False`
- `save_agent` with existing name overwrites (update semantics, preserves `created_at`)
- `get_agent` with unknown name returns `None`
- `save_agent` with invalid slug raises `ValueError`

### `tests/test_custom_agent_node.py` (mock LLM)
- Node uses `system_prompt` from definition as first message
- Node filters tools to `tool_names` list only
- Node returns content in `tool_results`
- Node returns error string when agent name not found
- Empty `tool_names` → LLM called with `tools=None`, no raise
- Disabled agent → returns error string (not raises)

### `tests/test_custom_agent_routing.py` (AsyncClient + mock LLM + mock supervisor)
- Keyword in `keywords` list routes to `custom_agent_node` (verify via `agent_routing` event)
- Disabled agent's keywords ignored — falls through to LLM classify
- `POST /api/agents` → agent appears in `GET /api/agents`
- `DELETE /api/agents/{name}` → agent absent from `GET /api/agents`
- `agents_updated` event fires on create and delete
- `POST /api/agents/{name}/toggle` flips `enabled` and returns new state
- Duplicate `name` on `POST` returns `409`
- Invalid slug returns `422`

---

## Out of Scope (Phase 2)

- Workflow agents (step sequences)
- Schedule triggers (cron)
- Event triggers (reminder_fired, status changes)
- Agent-to-agent chaining
- Custom agent versioning / history
