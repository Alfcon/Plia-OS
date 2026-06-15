# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e . --no-deps

# Run
python core/main.py          # dashboard at http://localhost:8000

# Test
source .venv/bin/activate
pytest                        # all 300+ tests
pytest --tb=short -q          # terse output
pytest tests/test_foo.py::test_bar -v   # single test
```

Optional extras:
```bash
pip install -e ".[fallback-openai]"     # cloud LLM fallback
pip install -e ".[fallback-anthropic]"
pip install -e ".[dramabox]"            # Dramabox TTS
pip install -e ".[playwright]"          # web scraping
```

## Architecture

### Startup flow (`core/main.py`)

`create_app()` is the ASGI factory (used by uvicorn and in tests via `AsyncClient(transport=ASGITransport(app=create_app()))`). It:
1. Calls `load_modules()` — imports every `modules/*.py` file, triggering `@tool` registrations
2. Calls `setup_event_forwarding()` — wires the event bus to WebSocket broadcast
3. Starts `VoicePipeline` and `run_reminder_loop()` as background asyncio tasks via lifespan

The dashboard and API remain available if the voice pipeline fails to load (e.g. no microphone).

### Request path (text chat)

`POST /api/chat` → `run_turn(messages)` in `core/supervisor.py` → LangGraph graph:

```
supervisor → [keyword route or LLM classify] → specialist agent → supervisor → respond → END
```

Supervisor first tries `_keyword_route()` (fast, no LLM call). If no match, it calls the LLM to classify into: `memory | web | code | calendar | home | reminder | respond`. Specialist agents run and return to supervisor; supervisor then routes to `respond` which calls the LLM with tool schemas and accumulated agent results.

### Event bus (`core/events.py`)

Simple in-process pub/sub. `emit(type, data)` calls all subscribers. Used for:
- `status` — pipeline state changes (armed/listening/processing/speaking)
- `transcript` — voice input/output text → dashboard chat
- `agent_routing` — which specialist handled a turn → dashboard badge
- `reminder_fired` — reminder poller → voice pipeline (announcement queue) + WebSocket
- `clear_history` — resets pipeline conversation state

### Config (`core/config.py`)

`PliaConfig` is a `@dataclass` persisted to `~/.plia/config.json` (override with `PLIA_CONFIG_FILE` env var). Use `get_config()` / `update_config(**kwargs)`. Enum-like fields are validated via `_LITERAL_CONSTRAINTS` dict — add any new constrained string field there, not in the dataclass annotation. `system_prompt_backup` is internal — blocked from `POST /api/config`, uses dedicated `/api/system-prompt/undo` and `/api/system-prompt/reset` endpoints.

### Tool registry (`core/registry.py`)

`@tool("description")` decorator registers a function for LLM function-calling. Tools are auto-discovered by `load_modules()` scanning `modules/*.py`. To add a tool: create or edit a file in `modules/`, decorate the function with `@tool`. The decorator auto-generates the OpenAI-compatible JSON schema from type hints.

### MemoryStore (`agents/memory_store.py`)

Singleton via `get_memory_store()`. SQLite at `~/.plia/memory.db` with three tables: `facts` (key/value), `history` (chat turns, capped at 500), `reminders` (id/message/fire_at/done). ChromaDB is optional — if unavailable or at init error, semantic recall degrades to an empty list (facts storage still works). All `MemoryStore` methods are synchronous; wrap with `asyncio.to_thread()` in async contexts.

### Voice pipeline (`voice/pipeline.py`)

State machine: armed → listening → processing → speaking → armed. Runs in a single asyncio task. Uses `get_stt_service()` (shared singleton with the `/api/voice/transcribe` endpoint — loading Whisper twice wastes ~200 MB RAM). Wake word detection uses openwakeword. Audio captured as int16 (avoids PipeWire float32 normalisation issues), normalised to float32 before STT. Echo suppression: wake word muted for 4s + audio duration after TTS playback.

### Dashboard (`dashboard/server.py` + `dashboard/static/index.html`)

Single FastAPI router mounted at `/`. WebSocket at `/ws` relays all `core.events` payloads to connected browser clients. `index.html` is a self-contained SPA — all JS is inline. Config is loaded once on page load via `GET /api/config` and saved field-by-field via `POST /api/config`. When adding a new config field to the UI: (1) add HTML controls, (2) add to `applyVoiceConfig()` / relevant apply function payload, (3) populate in the `fetch('/api/config').then(cfg => {...})` block around line 529.

### Testing patterns

`conftest.py` has three `autouse` fixtures that run for every test:
- `isolate_config_file` — redirects `_CONFIG_FILE` to a temp path (tests never touch `~/.plia/`)
- `reset_registry` — clears tool registrations before/after each test
- `reset_events` — clears event subscribers before/after each test

API endpoint tests use `httpx.AsyncClient(transport=ASGITransport(app=create_app()))`. Mock the LLM with `respx` or patch `agents.llm.call_llm`. Mock MemoryStore methods with `unittest.mock.patch("agents.memory_store.get_memory_store", return_value=mock)`.
