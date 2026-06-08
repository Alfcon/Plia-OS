# Memory Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the memory agent stub with a real SQLite + ChromaDB persistent memory layer that stores conversation history, key/value facts, and performs semantic recall.

**Architecture:** `agents/memory_store.py` owns all storage (SQLite + ChromaDB); `agents/memory.py` is a thin LangGraph node that parses the user's intent and calls the store; `core/supervisor.py` gains two hooks in `run_turn()` — inject memory context before graph invocation, auto-save user+assistant turns after. ChromaDB degrades gracefully: if Ollama's nomic-embed-text is unavailable, recall falls back to recent SQLite history.

**Tech Stack:** Python sqlite3 (stdlib), chromadb>=0.4, LangGraph (existing), Ollama nomic-embed-text embeddings

---

## File Structure

```
agents/
  memory_store.py   NEW  — MemoryStore class + get_memory_store() singleton
  memory.py         MOD  — replace stub with real LangGraph node

core/
  supervisor.py     MOD  — run_turn(): inject memory_context, auto-save turns

pyproject.toml      MOD  — add chromadb>=0.4 to main deps

tests/agents/
  test_memory_store.py  NEW  — MemoryStore unit tests (tmp_path, no side effects)
  test_memory_node.py   NEW  — memory_node unit tests (mocked store)
  test_supervisor.py    MOD  — add auto-save and context-injection tests
```

---

### Task 1: agents/memory_store.py — SQLite layer

**Files:**
- Modify: `pyproject.toml`
- Create: `agents/memory_store.py`
- Create: `tests/agents/test_memory_store.py`

- [ ] **Step 1: Add chromadb to dependencies**

In `pyproject.toml`, add `"chromadb>=0.4"` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "sounddevice>=0.5",
    "numpy>=1.26",
    "openwakeword>=0.4",
    "faster-whisper>=1.0",
    "kokoro>=0.9",
    "chatterbox-tts>=0.1",
    "scipy>=1.13",
    "langgraph>=0.2",
    "chromadb>=0.4",
]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/agents/test_memory_store.py`:

```python
import pytest
from agents.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db = str(tmp_path / "memory.db")
    chroma = str(tmp_path / "chroma")
    return MemoryStore(db_path=db, chroma_path=chroma)


def test_remember_and_get_fact(store):
    store.remember("user.name", "Alfcon")
    assert store.get_fact("user.name") == "Alfcon"


def test_remember_overwrites_existing(store):
    store.remember("key", "first")
    store.remember("key", "second")
    assert store.get_fact("key") == "second"


def test_forget_removes_fact(store):
    store.remember("key", "value")
    store.forget("key")
    assert store.get_fact("key") is None


def test_forget_nonexistent_is_safe(store):
    store.forget("does_not_exist")  # must not raise


def test_add_turn_and_recall_fallback(store):
    store.add_turn("user", "what is the weather")
    store.add_turn("assistant", "it is sunny")
    results = store.recall("weather")
    assert any("weather" in r or "sunny" in r for r in results)


def test_history_pruned_at_cap(store):
    for i in range(510):
        store.add_turn("user", f"message {i}")
    import sqlite3
    with sqlite3.connect(store._db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    assert count <= 500


def test_recall_returns_list(store):
    results = store.recall("anything")
    assert isinstance(results, list)
```

- [ ] **Step 3: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/agents/test_memory_store.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.memory_store'`

- [ ] **Step 4: Create agents/memory_store.py**

```python
from __future__ import annotations
import os
import sqlite3
import time
from datetime import datetime, timezone

_HISTORY_CAP = 500


class MemoryStore:
    def __init__(self, db_path: str, chroma_path: str, ollama_url: str = "http://localhost:11434") -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db_path = db_path
        self._chroma_path = chroma_path
        self._ollama_url = ollama_url
        self._collection = None
        self._init_db()
        self._init_chroma()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    fire_at TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0
                );
            """)

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
            os.makedirs(self._chroma_path, exist_ok=True)
            ef = OllamaEmbeddingFunction(
                url=f"{self._ollama_url}/api/embed",
                model_name="nomic-embed-text",
            )
            client = chromadb.PersistentClient(path=self._chroma_path)
            self._collection = client.get_or_create_collection(
                "conversations",
                embedding_function=ef,
            )
        except Exception:
            self._collection = None

    def remember(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO facts (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )

    def get_fact(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def forget(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM facts WHERE key = ?", (key,))

    def add_turn(self, role: str, content: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO history (role, content, ts) VALUES (?, ?, ?)",
                (role, content, now),
            )
            count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            if count > _HISTORY_CAP:
                excess = count - _HISTORY_CAP
                conn.execute(
                    "DELETE FROM history WHERE id IN "
                    "(SELECT id FROM history ORDER BY id ASC LIMIT ?)",
                    (excess,),
                )
        self._chroma_add(role, content)

    def recall(self, query: str, n_results: int = 5) -> list[str]:
        if self._collection is not None:
            try:
                results = self._collection.query(query_texts=[query], n_results=n_results)
                docs = results.get("documents", [[]])[0]
                if docs:
                    return docs
            except Exception:
                pass
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM history ORDER BY id DESC LIMIT ?",
                (n_results,),
            ).fetchall()
        return [f"{r}: {c}" for r, c in reversed(rows)]

    def _chroma_add(self, role: str, content: str) -> None:
        if self._collection is None:
            return
        try:
            doc_id = f"{role}_{int(time.time() * 1_000_000)}"
            self._collection.add(documents=[f"{role}: {content}"], ids=[doc_id])
        except Exception:
            pass


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        from core.config import get_config
        config = get_config()
        db_path = os.path.join(config.memory_dir, "memory.db")
        chroma_path = os.path.join(config.memory_dir, "chroma")
        _store = MemoryStore(db_path, chroma_path, config.ollama_url)
    return _store


def reset_memory_store() -> None:
    """Test helper — clears the singleton so each test gets a fresh store."""
    global _store
    _store = None
```

- [ ] **Step 5: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_memory_store.py -v
```

Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml agents/memory_store.py tests/agents/test_memory_store.py
git commit -m "feat: add MemoryStore with SQLite persistence and ChromaDB fallback"
```

---

### Task 2: agents/memory.py — real LangGraph node

**Files:**
- Modify: `agents/memory.py`
- Create: `tests/agents/test_memory_node.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_memory_node.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.memory import memory_node
from agents.memory_store import reset_memory_store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    reset_memory_store()
    with patch("agents.memory.get_memory_store") as mock_gsm:
        mock_store = MagicMock()
        mock_store.recall.return_value = ["user: my dog is named Rex"]
        mock_store.get_fact.return_value = None
        mock_gsm.return_value = mock_store
        yield mock_store
    reset_memory_store()


def _state(user_text):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_recall_returns_context(isolated_store):
    isolated_store.recall.return_value = ["user: my dog is Rex"]
    update = await memory_node(_state("what is my dog's name"))
    assert update["active_agent"] == "memory"
    assert "Rex" in update["memory_context"] or any("Rex" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_remember_calls_store(isolated_store):
    with patch("agents.memory.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"remember","key":"user.dog","value":"Rex"}'}
        update = await memory_node(_state("remember my dog is named Rex"))
    isolated_store.remember.assert_called_once_with("user.dog", "Rex")
    assert update["active_agent"] == "memory"


@pytest.mark.asyncio
async def test_forget_calls_store(isolated_store):
    with patch("agents.memory.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"forget","key":"user.dog","value":""}'}
        update = await memory_node(_state("forget my dog's name"))
    isolated_store.forget.assert_called_once_with("user.dog")
    assert update["active_agent"] == "memory"


@pytest.mark.asyncio
async def test_llm_parse_error_falls_back_to_recall(isolated_store):
    with patch("agents.memory.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await memory_node(_state("what do you remember about me"))
    assert update["active_agent"] == "memory"
    assert isinstance(update["tool_results"], list)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/agents/test_memory_node.py -v 2>&1 | head -20
```

Expected: FAIL — `memory_node` is still the stub.

- [ ] **Step 3: Replace the stub in agents/memory.py**

```python
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.memory_store import get_memory_store

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the user memory request. Output JSON with exactly three keys: "
    '"op" ("remember", "recall", or "forget"), '
    '"key" (short identifier string), '
    '"value" (the fact to store, or empty string). '
    "Output only valid JSON, no explanation."
)


async def memory_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    # Ask LLM to classify the memory operation
    try:
        parse_messages = [
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ]
        msg = await call_llm(parse_messages)
        parsed = json.loads(msg.get("content", "{}"))
        op = parsed.get("op", "recall")
        key = parsed.get("key", last_user[:80])
        value = parsed.get("value", "")
    except Exception:
        op, key, value = "recall", last_user[:80], ""

    store = get_memory_store()

    if op == "remember" and key and value:
        store.remember(key, value)
        result = f"Remembered: {key} = {value}"
        return {
            "tool_results": state["tool_results"] + [result],
            "active_agent": "memory",
        }

    if op == "forget" and key:
        store.forget(key)
        result = f"Forgot: {key}"
        return {
            "tool_results": state["tool_results"] + [result],
            "active_agent": "memory",
        }

    # Default: recall
    snippets = store.recall(last_user)
    context = "\n".join(snippets)
    logger.info("Memory recall: %d snippets", len(snippets))
    return {
        "tool_results": state["tool_results"] + [f"[memory]\n{context}"],
        "active_agent": "memory",
        "memory_context": context,
    }
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_memory_node.py -v
```

Expected: 4 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all tests pass (≥101)

- [ ] **Step 6: Commit**

```bash
git add agents/memory.py tests/agents/test_memory_node.py
git commit -m "feat: implement memory agent node with remember/recall/forget operations"
```

---

### Task 3: Wire memory into core/supervisor.py

Inject `memory_context` before graph invocation (based on the last user message), and auto-save user + assistant turns after each `run_turn()` completes.

**Files:**
- Modify: `core/supervisor.py`
- Modify: `tests/agents/test_supervisor.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/agents/test_supervisor.py`:

```python
@pytest.mark.asyncio
async def test_run_turn_auto_saves_turns():
    """After run_turn, both user and assistant turns are saved to the memory store."""
    messages = [
        {"role": "system", "content": "You are Plia."},
        {"role": "user", "content": "hello"},
    ]
    mock_store = MagicMock()
    mock_store.recall.return_value = []

    with patch("core.supervisor.get_memory_store", return_value=mock_store), \
         patch("agents.llm.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = [
            # supervisor node: classify intent → respond
            {"message": {"role": "assistant", "content": "respond", "tool_calls": None}},
            # respond node: final answer
            {"message": {"role": "assistant", "content": "Hello there!", "tool_calls": None}},
        ]
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        response, _ = await run_turn(messages)

    calls = [str(c) for c in mock_store.add_turn.call_args_list]
    assert any("user" in c and "hello" in c for c in calls)
    assert any("assistant" in c and "Hello there!" in c for c in calls)


@pytest.mark.asyncio
async def test_run_turn_injects_memory_context():
    """memory_context in state is populated from store.recall before graph runs."""
    messages = [
        {"role": "system", "content": "You are Plia."},
        {"role": "user", "content": "what is my name"},
    ]
    mock_store = MagicMock()
    mock_store.recall.return_value = ["user: my name is Alfcon"]

    captured_state = {}

    async def fake_invoke(state, *args, **kwargs):
        captured_state.update(state)
        return {
            "messages": state["messages"] + [{"role": "assistant", "content": "Alfcon"}],
            "tool_results": [],
        }

    with patch("core.supervisor.get_memory_store", return_value=mock_store), \
         patch("core.supervisor._graph") as mock_graph:
        mock_graph.ainvoke = fake_invoke
        await run_turn(messages)

    assert "my name is Alfcon" in captured_state.get("memory_context", "")
```

At the top of `tests/agents/test_supervisor.py`, add this import:

```python
from unittest.mock import patch, MagicMock, AsyncMock
```

(It likely already has `patch` and `AsyncMock`; add `MagicMock` if missing.)

- [ ] **Step 2: Run new tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/agents/test_supervisor.py::test_run_turn_auto_saves_turns tests/agents/test_supervisor.py::test_run_turn_injects_memory_context -v 2>&1 | head -30
```

Expected: FAIL — `run_turn` doesn't call `get_memory_store` yet.

- [ ] **Step 3: Modify core/supervisor.py — add import and update run_turn**

Add this import at the top of `core/supervisor.py` (after existing imports):

```python
from agents.memory_store import get_memory_store
```

Replace the `run_turn` function (currently at the bottom of the file):

```python
async def run_turn(messages: list[dict]) -> tuple[str, list[dict]]:
    config = get_config()
    store = get_memory_store()

    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    memory_context = "\n".join(store.recall(last_user)) if last_user else ""

    state = AgentState(
        messages=list(messages),
        memory_context=memory_context,
        active_agent=None,
        search_provider=config.web_search_default,
        hop_count=0,
        tool_results=[],
    )
    result = await _graph.ainvoke(state)
    final_messages = result["messages"]
    last = final_messages[-1]
    response = last.get("content", "")

    if last_user:
        store.add_turn("user", last_user)
    if response:
        store.add_turn("assistant", response)

    return response, final_messages
```

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all tests pass (≥103 — the 101 existing plus 2 new supervisor tests)

If existing supervisor tests fail because `get_memory_store` is now called but not mocked, patch it in the `conftest.py` or add an autouse fixture to `tests/agents/test_supervisor.py`:

```python
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def mock_memory_store():
    mock = MagicMock()
    mock.recall.return_value = []
    with patch("core.supervisor.get_memory_store", return_value=mock):
        yield mock
```

Place this fixture BEFORE the new tests. The new tests that need custom store behaviour override it with their own `patch`.

- [ ] **Step 5: Commit**

```bash
git add core/supervisor.py tests/agents/test_supervisor.py
git commit -m "feat: inject memory context and auto-save turns in supervisor run_turn"
```

---

### Task 4: Install dependency and smoke test

- [ ] **Step 1: Install chromadb**

```bash
pip install chromadb>=0.4
```

Or if using hatch/uv:

```bash
.venv/bin/pip install "chromadb>=0.4"
```

- [ ] **Step 2: Run full suite one final time**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all tests pass

- [ ] **Step 3: Verify MemoryStore creates its DB file**

```bash
.venv/bin/python -c "
from agents.memory_store import get_memory_store
s = get_memory_store()
s.remember('test.key', 'hello world')
print('fact:', s.get_fact('test.key'))
s.add_turn('user', 'hello')
print('recall:', s.recall('hello'))
print('OK')
"
```

Expected output:
```
fact: hello world
recall: ['user: hello']
OK
```

- [ ] **Step 4: Commit if pyproject.toml wasn't already updated in Task 1**

(Only needed if chromadb was not committed in Task 1.)

```bash
git add pyproject.toml
git commit -m "chore: pin chromadb>=0.4 in project deps"
```
