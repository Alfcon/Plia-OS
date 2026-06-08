# Multiagent Plia-OS Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single `core/agent.py` loop with a LangGraph supervisor that routes voice requests to specialist agents (memory, web, code, calendar, home).

**Architecture:** Pure LangGraph StateGraph — supervisor node classifies intent and routes to worker nodes. Drop-in replacement: `core/supervisor.py` exposes the same `run_turn(messages)` interface so `voice/pipeline.py` is untouched. Each node tries Ollama first, falls back to a configured cloud provider on failure.

**Tech Stack:** LangGraph, ChromaDB, SQLite, DuckDuckGo Search, Google Custom Search, Playwright, icalendar, Ollama (primary LLM), OpenAI/Anthropic (fallback)

---

## Architecture

### Data Flow

```
VoicePipeline (unchanged)
  wake → STT → run_turn() → TTS → armed
                  │
                  ▼  (same interface, drop-in)
core/supervisor.py — LangGraph StateGraph
  Supervisor Node: classify intent → route
    ├─ memory   → agents/memory.py   → SQLite + ChromaDB
    ├─ web      → agents/web.py      → DDG / Google / Playwright
    ├─ code     → agents/code.py     → subprocess sandbox
    ├─ calendar → agents/calendar.py → ICS / Google Calendar
    ├─ home     → agents/home.py     → stub (Home Assistant later)
    └─ respond  → return text to pipeline
```

### AgentState (TypedDict)

```python
class AgentState(TypedDict):
    messages: list[dict]        # full conversation history
    memory_context: str         # injected semantic recall snippets
    active_agent: str | None    # last node that ran
    search_provider: str        # "ddg" | "google" | "playwright"
    hop_count: int              # max 5; prevents infinite routing
    tool_results: list[str]     # accumulated agent outputs
```

### File Structure

```
core/
  agent.py          ← replaced by supervisor.py (kept for reference, not imported)
  supervisor.py     ← NEW: LangGraph StateGraph + run_turn()
  config.py         ← add: fallback_provider, fallback_model, fallback_api_key,
                           web_search_default, google_search_api_key,
                           google_search_cx, memory_dir
agents/             ← NEW package
  __init__.py
  llm.py            ← shared Ollama-primary / cloud-fallback call_llm()
  memory.py         ← SQLite + ChromaDB agent node
  web.py            ← DDG / Google / Playwright node
  code.py           ← subprocess sandbox node
  calendar.py       ← ICS / Google Calendar node
  home.py           ← stub
```

---

## Agent Specifications

### Supervisor Node
- Calls `call_llm()` with an intent-classification system prompt
- Parses intent into one of: `memory | web | code | calendar | home | respond`
- Routes to the matching node via LangGraph conditional edges
- On `respond`: returns `(text, updated_messages)` to the voice pipeline
- Hard limit: `hop_count >= 5` forces `respond` regardless of intent

### Memory Agent (`agents/memory.py`)
- **SQLite** (`~/.plia/memory.db`): structured key/value facts and conversation history
  - Tables: `facts(key, value, updated_at)`, `history(id, role, content, ts)`, `reminders(id, message, fire_at, done)`
  - History capped at 500 turns; older rows pruned on insert
- **ChromaDB** (`~/.plia/chroma/`): vector store for semantic recall
  - Collection: `conversations` — each turn embedded via `nomic-embed-text` (Ollama)
  - On recall query: top-5 semantically similar turns injected into `AgentState.memory_context`
- **Tools**: `remember(key, value)`, `recall(query)`, `forget(key)`
- **Auto-save**: after every `run_turn()`, extract facts from the response and store

### Web Agent (`agents/web.py`)
- Provider selection: user can specify at query time ("search with Google…") or `config.web_search_default` is used
- **DuckDuckGo**: no API key, default provider, uses `duckduckgo-search` package
- **Google Custom Search**: requires `google_search_api_key` + `google_search_cx` in config
- **Playwright**: full page scrape for "read this page" / "open this URL" requests
- Returns: top 3 results as plain text, passed back to supervisor via `tool_results`

### Code Agent (`agents/code.py`)
- Sandbox: isolated `tempfile.mkdtemp()`, 30s timeout, no network, restricted imports
- Blocked: `os.system`, `subprocess` with `shell=True`, `socket`, `urllib`
- Languages: Python (exec), shell (bash -c with restricted PATH)
- Returns: stdout + stderr, truncated to 2000 chars

### Calendar Agent (`agents/calendar.py`)
- **Local ICS**: reads/writes `~/.plia/calendar.ics` by default (no credentials needed)
- **Google Calendar**: optional; requires OAuth token path in config
- Tools: `add_event(title, date, time, duration)`, `list_events(start, end)`, `delete_event(uid)`

### Home Agent (`agents/home.py`)
- Stub: accepts any command, responds "Home automation not configured yet"
- Fully wired into supervisor graph so future implementation is a drop-in
- Future backend: Home Assistant REST API

### Shared LLM Helper (`agents/llm.py`)
```
call_llm(messages, config):
  1. POST to Ollama (config.ollama_url + config.ollama_model)
  2. On timeout / HTTP error / empty response:
     → try config.fallback_provider (openai | anthropic | "")
  3. If no fallback configured → raise RuntimeError with clear message
```

---

## Config Additions

| Field | Default | Description |
|-------|---------|-------------|
| `fallback_provider` | `""` | `"openai"` \| `"anthropic"` \| `""` |
| `fallback_model` | `""` | e.g. `"gpt-4o-mini"` |
| `fallback_api_key` | `""` | never logged |
| `web_search_default` | `"ddg"` | `"ddg"` \| `"google"` \| `"playwright"` |
| `google_search_api_key` | `""` | Google Custom Search API key |
| `google_search_cx` | `""` | Google Custom Search engine ID |
| `memory_dir` | `"~/.plia"` | root for SQLite, ChromaDB, ICS |

---

## Error Handling

| Failure | Recovery |
|---------|----------|
| Ollama timeout | Fallback to cloud LLM |
| Cloud LLM fails | "I can't reach my brain right now" |
| Web search error | "Search unavailable, try again" |
| Code sandbox timeout/OOM | "Execution timed out" |
| Memory DB corrupt | Log + continue without memory context |
| Hop limit (5) reached | Supervisor forces direct response |
| Any agent raises | Caught at supervisor, logged, graceful reply |

---

## Observability

- Each node emits: `events.emit("agent", {"node": "web", "state": "running|done|error", "latency_ms": N})`
- Dashboard status badge shows active agent name during processing
- New endpoint: `GET /api/agent/trace` — last 20 agent node executions with latencies
- LangGraph graph traces available in debug mode via `LANGGRAPH_DEBUG=1`

---

## Testing Strategy

- **Unit**: each agent node tested in isolation with mocked `call_llm()` and mocked tools
- **Supervisor routing**: assert correct node chosen for each intent string
- **Memory**: SQLite and ChromaDB use `tmp_path` fixtures, no side effects
- **Code sandbox**: run safe snippets; assert timeout/block for unsafe ones
- **LLM fallback**: mock Ollama to fail, assert cloud fallback triggers
- **Integration**: full `run_turn()` with mocked LLM, assert correct response shape
- All existing 89 tests continue to pass — voice pipeline untouched

---

## Implementation Order

1. `core/supervisor.py` + `agents/llm.py` — backbone, replaces `agent.py`
2. `agents/memory.py` — SQLite + ChromaDB
3. `agents/web.py` — DDG + Google + Playwright
4. `agents/code.py` — subprocess sandbox
5. `agents/calendar.py` — ICS + Google Calendar
6. `agents/home.py` — stub
7. Dashboard agent panel — live agent status in UI
8. Config additions + dashboard controls for fallback/web provider
