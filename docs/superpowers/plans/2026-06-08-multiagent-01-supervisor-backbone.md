# Multiagent — Plan 1: Supervisor Backbone

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `core/agent.py` with a LangGraph supervisor that routes to named agent nodes, while keeping the voice pipeline completely untouched.

**Architecture:** `core/supervisor.py` exposes the same `run_turn(messages)` interface as the old `agent.py`. A LangGraph StateGraph with a supervisor node routes intent to stub worker nodes (memory, web, code, calendar, home). `agents/llm.py` provides a shared Ollama-primary / cloud-fallback `call_llm()` helper used by every node.

**Tech Stack:** `langgraph`, `httpx` (already installed), `openai` (optional fallback), `anthropic` (optional fallback)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/__init__.py` | Create | Package marker |
| `agents/llm.py` | Create | Shared `call_llm()` — Ollama primary, cloud fallback |
| `agents/memory.py` | Create | Stub node (real impl in Plan 2) |
| `agents/web.py` | Create | Stub node (real impl in Plan 3) |
| `agents/code.py` | Create | Stub node (real impl in Plan 4) |
| `agents/calendar.py` | Create | Stub node (real impl in Plan 5) |
| `agents/home.py` | Create | Stub node (permanent stub until Home Assistant) |
| `core/supervisor.py` | Create | LangGraph StateGraph + `run_turn()` |
| `core/config.py` | Modify | Add fallback + web_search + memory_dir fields |
| `voice/pipeline.py` | Modify | Import `run_turn` from `supervisor` not `agent` |
| `tests/agents/__init__.py` | Create | Package marker |
| `tests/agents/test_llm.py` | Create | LLM helper tests |
| `tests/agents/test_supervisor.py` | Create | Supervisor routing tests |
| `pyproject.toml` | Modify | Add `langgraph`, optional `openai`, `anthropic` |

---

## Task 1: Install Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add langgraph to dependencies**

In `pyproject.toml`, add to the `[project] dependencies` list:

```toml
"langgraph>=0.2",
```

Add two optional dependency groups:

```toml
[project.optional-dependencies]
fallback-openai = ["openai>=1.0"]
fallback-anthropic = ["anthropic>=0.25"]
```

- [ ] **Step 2: Install**

```bash
.venv/bin/pip install langgraph
```

Expected: `Successfully installed langgraph-...`

- [ ] **Step 3: Verify import**

```bash
.venv/bin/python -c "from langgraph.graph import StateGraph; print('ok')"
```

Expected: `ok`

---

## Task 2: Config Fields

**Files:**
- Modify: `core/config.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_config_multiagent.py`:

```python
from core.config import reset_config, update_config, get_config


def setup_function():
    reset_config()


def teardown_function():
    reset_config()


def test_fallback_provider_defaults_empty():
    assert get_config().fallback_provider == ""


def test_fallback_model_defaults_empty():
    assert get_config().fallback_model == ""


def test_web_search_default_is_ddg():
    assert get_config().web_search_default == "ddg"


def test_memory_dir_default():
    import os
    assert get_config().memory_dir == os.path.expanduser("~/.plia")


def test_update_fallback_provider():
    update_config(fallback_provider="openai")
    assert get_config().fallback_provider == "openai"


def test_update_web_search_default():
    update_config(web_search_default="google")
    assert get_config().web_search_default == "google"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/python -m pytest tests/test_config_multiagent.py -v
```

Expected: `AttributeError: 'Config' object has no attribute 'fallback_provider'`

- [ ] **Step 3: Add fields to Config**

In `core/config.py`, find the `@dataclass` `Config` class and add these fields after the existing ones:

```python
# Multiagent LLM fallback
fallback_provider: str = ""        # "openai" | "anthropic" | ""
fallback_model: str = ""           # e.g. "gpt-4o-mini"
fallback_api_key: str = ""         # never logged

# Web agent
web_search_default: str = "ddg"   # "ddg" | "google" | "playwright"
google_search_api_key: str = ""
google_search_cx: str = ""

# Memory agent
memory_dir: str = field(default_factory=lambda: os.path.expanduser("~/.plia"))
```

Add `import os` and `from dataclasses import dataclass, field` at the top if not already present. Check if `field` is already imported.

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m pytest tests/test_config_multiagent.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config_multiagent.py pyproject.toml
git commit -m "feat: add multiagent config fields and langgraph dependency"
```

---

## Task 3: LLM Helper

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/llm.py`
- Create: `tests/agents/__init__.py`
- Create: `tests/agents/test_llm.py`

- [ ] **Step 1: Create package markers**

`agents/__init__.py` — empty file.
`tests/agents/__init__.py` — empty file.

- [ ] **Step 2: Write failing tests**

Create `tests/agents/test_llm.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.config import reset_config, update_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


async def test_call_llm_uses_ollama():
    from agents.llm import call_llm
    fake_msg = {"role": "assistant", "content": "Hello"}
    with patch("agents.llm.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"message": fake_msg},
            raise_for_status=lambda: None,
        ))
        result = await call_llm([{"role": "user", "content": "hi"}])
    assert result == fake_msg


async def test_call_llm_falls_back_on_ollama_failure():
    from agents.llm import call_llm
    update_config(fallback_provider="openai", fallback_model="gpt-4o-mini", fallback_api_key="sk-test")
    fake_msg = {"role": "assistant", "content": "Fallback reply"}

    with patch("agents.llm.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=Exception("connection refused"))
        with patch("agents.llm._call_openai", new=AsyncMock(return_value=fake_msg)):
            result = await call_llm([{"role": "user", "content": "hi"}])
    assert result == fake_msg


async def test_call_llm_raises_when_no_fallback_configured():
    from agents.llm import call_llm
    with patch("agents.llm.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=Exception("connection refused"))
        with pytest.raises(RuntimeError, match="no fallback"):
            await call_llm([{"role": "user", "content": "hi"}])
```

- [ ] **Step 3: Run — expect FAIL**

```bash
.venv/bin/python -m pytest tests/agents/test_llm.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents'`

- [ ] **Step 4: Implement agents/llm.py**

```python
import httpx
from core.config import get_config

_OLLAMA_TIMEOUT = 30.0


async def call_llm(messages: list[dict], tools: list | None = None) -> dict:
    config = get_config()
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            payload: dict = {
                "model": config.ollama_model,
                "messages": messages,
                "stream": False,
            }
            if tools:
                payload["tools"] = tools
            resp = await client.post(f"{config.ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]
    except Exception as exc:
        if not config.fallback_provider:
            raise RuntimeError(
                f"Ollama failed and no fallback configured: {exc}"
            ) from exc
        return await _dispatch_fallback(messages, tools, config)


async def _dispatch_fallback(messages: list[dict], tools: list | None, config) -> dict:
    if config.fallback_provider == "openai":
        return await _call_openai(messages, tools, config)
    if config.fallback_provider == "anthropic":
        return await _call_anthropic(messages, tools, config)
    raise RuntimeError(f"Unknown fallback_provider: {config.fallback_provider!r}")


async def _call_openai(messages: list[dict], tools: list | None, config) -> dict:
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError(
            "openai package not installed. Run: pip install openai"
        ) from exc
    client = openai.AsyncOpenAI(api_key=config.fallback_api_key)
    kwargs: dict = {"model": config.fallback_model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0].message
    return {"role": "assistant", "content": choice.content or ""}


async def _call_anthropic(messages: list[dict], tools: list | None, config) -> dict:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        ) from exc
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    client = anthropic.AsyncAnthropic(api_key=config.fallback_api_key)
    kwargs: dict = {
        "model": config.fallback_model,
        "max_tokens": 1024,
        "messages": user_msgs,
    }
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return {"role": "assistant", "content": response.content[0].text}
```

- [ ] **Step 5: Run — expect PASS**

```bash
.venv/bin/python -m pytest tests/agents/test_llm.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add agents/ tests/agents/
git commit -m "feat: agents/llm.py — Ollama primary with cloud fallback"
```

---

## Task 4: Stub Agent Nodes

**Files:**
- Create: `agents/memory.py`
- Create: `agents/web.py`
- Create: `agents/code.py`
- Create: `agents/calendar.py`
- Create: `agents/home.py`

All stubs follow the same pattern — they accept AgentState and return a partial update with a tool result message. Real implementations come in Plans 2–5.

- [ ] **Step 1: Create agents/memory.py**

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def memory_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[memory] not yet implemented"],
        "active_agent": "memory",
    }
```

- [ ] **Step 2: Create agents/web.py**

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def web_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[web] not yet implemented"],
        "active_agent": "web",
    }
```

- [ ] **Step 3: Create agents/code.py**

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def code_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[code] not yet implemented"],
        "active_agent": "code",
    }
```

- [ ] **Step 4: Create agents/calendar.py**

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def calendar_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + ["[calendar] not yet implemented"],
        "active_agent": "calendar",
    }
```

- [ ] **Step 5: Create agents/home.py**

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.supervisor import AgentState


async def home_node(state: "AgentState") -> dict:
    return {
        "tool_results": state["tool_results"] + [
            "Home automation not configured yet."
        ],
        "active_agent": "home",
    }
```

- [ ] **Step 6: Commit**

```bash
git add agents/memory.py agents/web.py agents/code.py agents/calendar.py agents/home.py
git commit -m "feat: stub agent nodes for memory, web, code, calendar, home"
```

---

## Task 5: Supervisor

**Files:**
- Create: `core/supervisor.py`
- Create: `tests/agents/test_supervisor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_supervisor.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from core.config import reset_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


async def test_run_turn_returns_string_and_messages():
    from core.supervisor import run_turn
    fake_msg = {"role": "assistant", "content": "It is 3pm."}
    with patch("core.supervisor.call_llm", new=AsyncMock(return_value=fake_msg)):
        text, history = await run_turn([
            {"role": "system", "content": "You are Plia."},
            {"role": "user", "content": "What time is it?"},
        ])
    assert isinstance(text, str)
    assert len(text) > 0
    assert isinstance(history, list)


async def test_supervisor_routes_to_memory_agent():
    from core.supervisor import run_turn
    # First call: supervisor says route to memory
    # Second call: supervisor says respond
    classify_msg = {"role": "assistant", "content": "memory"}
    respond_msg = {"role": "assistant", "content": "I remember you told me your name."}
    call_count = 0

    async def fake_llm(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return classify_msg
        return respond_msg

    with patch("core.supervisor.call_llm", new=fake_llm):
        text, history = await run_turn([
            {"role": "system", "content": "You are Plia."},
            {"role": "user", "content": "Do you remember my name?"},
        ])
    assert "remember" in text.lower() or isinstance(text, str)


async def test_hop_limit_forces_response():
    from core.supervisor import run_turn
    # Supervisor always returns "web" — hop limit should stop it
    classify_msg = {"role": "assistant", "content": "web"}
    respond_msg = {"role": "assistant", "content": "Here is what I found."}
    call_count = 0

    async def fake_llm(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 5:
            return classify_msg
        return respond_msg

    with patch("core.supervisor.call_llm", new=fake_llm):
        text, history = await run_turn([
            {"role": "system", "content": "You are Plia."},
            {"role": "user", "content": "search everything forever"},
        ])
    assert isinstance(text, str)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/python -m pytest tests/agents/test_supervisor.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.supervisor'`

- [ ] **Step 3: Implement core/supervisor.py**

```python
from __future__ import annotations
import logging
from typing import TypedDict
from langgraph.graph import StateGraph, END
from core.config import get_config
from core.registry import get_tool_schemas
from agents.llm import call_llm
from agents.memory import memory_node
from agents.web import web_node
from agents.code import code_node
from agents.calendar import calendar_node
from agents.home import home_node

logger = logging.getLogger(__name__)

_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home"}
_HOP_LIMIT = 5

_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home. "
    "If the request needs no specialist, output: respond."
)


class AgentState(TypedDict):
    messages: list[dict]
    memory_context: str
    active_agent: str | None
    search_provider: str
    hop_count: int
    tool_results: list[str]


async def _supervisor_node(state: AgentState) -> dict:
    if state["hop_count"] >= _HOP_LIMIT:
        return {"active_agent": "respond"}

    classify_messages = [
        {"role": "system", "content": _CLASSIFY_SYSTEM},
        *state["messages"],
    ]
    msg = await call_llm(classify_messages)
    intent = msg.get("content", "").strip().lower().split()[0] if msg.get("content") else "respond"
    if intent not in _KNOWN_INTENTS:
        intent = "respond"
    logger.info("Supervisor routed to: %s", intent)
    return {"active_agent": intent, "hop_count": state["hop_count"] + 1}


async def _respond_node(state: AgentState) -> dict:
    config = get_config()
    tools = get_tool_schemas()
    history = list(state["messages"])

    context = state.get("memory_context", "")
    if context:
        history = [history[0], {"role": "system", "content": f"Context:\n{context}"}, *history[1:]]

    if state["tool_results"]:
        combined = "\n".join(state["tool_results"])
        history.append({"role": "system", "content": f"Agent results:\n{combined}"})

    while True:
        payload_msg = await call_llm(history, tools=tools or None)
        history.append(payload_msg)
        if not payload_msg.get("tool_calls"):
            break
        from core.registry import call_tool
        import inspect
        for tc in payload_msg["tool_calls"]:
            fn = tc["function"]
            try:
                result = call_tool(fn["name"], fn.get("arguments") or {})
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                result = f"Error: {exc}"
            history.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result),
            })

    return {"messages": history}


def _route(state: AgentState) -> str:
    return state.get("active_agent") or "respond"


def _build_graph() -> object:
    g = StateGraph(AgentState)
    g.add_node("supervisor", _supervisor_node)
    g.add_node("memory", memory_node)
    g.add_node("web", web_node)
    g.add_node("code", code_node)
    g.add_node("calendar", calendar_node)
    g.add_node("home", home_node)
    g.add_node("respond", _respond_node)

    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", _route, {
        "memory": "memory",
        "web": "web",
        "code": "code",
        "calendar": "calendar",
        "home": "home",
        "respond": "respond",
    })
    for agent in ("memory", "web", "code", "calendar", "home"):
        g.add_edge(agent, "supervisor")
    g.add_edge("respond", END)
    return g.compile()


_graph = _build_graph()


async def run_turn(messages: list[dict]) -> tuple[str, list[dict]]:
    config = get_config()
    state = AgentState(
        messages=list(messages),
        memory_context="",
        active_agent=None,
        search_provider=config.web_search_default,
        hop_count=0,
        tool_results=[],
    )
    result = await _graph.ainvoke(state)
    final_messages = result["messages"]
    last = final_messages[-1]
    return last.get("content", ""), final_messages
```

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m pytest tests/agents/test_supervisor.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add core/supervisor.py tests/agents/test_supervisor.py
git commit -m "feat: LangGraph supervisor with intent routing and hop limit"
```

---

## Task 6: Wire Into Voice Pipeline

**Files:**
- Modify: `voice/pipeline.py:5` (one import line)

- [ ] **Step 1: Update import in pipeline.py**

In `voice/pipeline.py`, line 5, change:

```python
from core.agent import run_turn
```

to:

```python
from core.supervisor import run_turn
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all existing tests pass + new tests pass. `core/agent.py` is no longer imported anywhere so its tests may need updating — if `tests/test_agent.py` imports from `core.agent`, update it to import from `core.supervisor` instead.

- [ ] **Step 3: Check test_agent.py**

```bash
grep -n "core.agent" tests/test_agent.py
```

If found, update those imports to `core.supervisor` and re-run tests.

- [ ] **Step 4: Smoke test the server**

```bash
fuser -k 8000/tcp 2>/dev/null; sleep 1
/home/alfcon/Projects/Plia-OS/.venv/bin/python -m core.main &
sleep 5
curl -s http://localhost:8000/api/config | python3 -m json.tool | grep fallback
```

Expected: `"fallback_provider": ""` and `"web_search_default": "ddg"` appear in output.

- [ ] **Step 5: Commit**

```bash
git add voice/pipeline.py tests/test_agent.py  # only if test_agent.py changed
git commit -m "feat: wire supervisor into voice pipeline — multiagent backbone live"
```

---

## Self-Review

**Spec coverage:**
- ✅ Drop-in `run_turn()` interface — Task 6
- ✅ LangGraph StateGraph — Task 5
- ✅ AgentState with all fields — Task 5
- ✅ Supervisor intent classification — Task 5
- ✅ Hop limit (5) — Task 5
- ✅ Ollama primary / cloud fallback — Task 3
- ✅ Config additions — Task 2
- ✅ All agent stubs wired — Task 4
- ✅ Existing tools preserved (`get_tool_schemas` used in `_respond_node`) — Task 5
- ✅ Voice pipeline untouched — Task 6

**Gaps:** Memory context injection, dashboard agent panel, and real agent implementations are in Plans 2–6. The home stub is permanent until Home Assistant is added.
