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
pytest                        # all 560+ tests
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

Pipeline is started via `core/pipeline_runner.py` (`start_pipeline()`), which calls `pipeline.load()` then `pipeline.start()`. The dashboard and API remain available if the voice pipeline fails to load (e.g. no microphone).

### Request path (text chat)

`POST /api/chat` → `run_turn(messages)` in `core/supervisor.py` → LangGraph graph:

```
supervisor → [keyword route or LLM classify] → specialist agent → supervisor → respond → END
```

Supervisor first tries `_keyword_route()` (fast, no LLM call). If no match, it calls the LLM to classify into: `memory | web | code | calendar | home | reminder | respond`. Specialist agents run and return to supervisor; supervisor then routes to `respond` which calls the LLM with tool schemas and accumulated agent results.

After each turn, supervisor dual-writes to both `agents/chat_history` and `agents/memory_store` (separate DBs — see below).

### Event bus (`core/events.py`)

Simple in-process pub/sub. `emit(type, data)` calls all subscribers. Used for:
- `status` — pipeline state changes (armed/listening/processing/speaking)
- `transcript` — voice input/output text → dashboard chat
- `agent_routing` — which specialist handled a turn → dashboard badge
- `reminder_fired` — reminder poller → voice pipeline (announcement queue) + WebSocket
- `clear_history` — resets pipeline conversation state

### Config (`core/config.py`)

`PliaConfig` is a `@dataclass` persisted to `~/.plia/config.json` (override with `PLIA_CONFIG_FILE` env var). Use `get_config()` / `update_config(**kwargs)`. Enum-like fields are validated via `_LITERAL_CONSTRAINTS` dict — add any new constrained string field there, not in the dataclass annotation. `system_prompt_backup` is internal — blocked from `POST /api/config`, uses dedicated `/api/system-prompt/undo` and `/api/system-prompt/reset` endpoints.

Key config fields (all persisted):
- LLM: `ollama_url`, `ollama_model`, `system_prompt`
- AirLLM: `airllm_model`, `airllm_compression` (`4bit | 8bit | none`)
- Fallback LLM: `fallback_provider`, `fallback_model`, `fallback_api_key`
- TTS: `tts_engine` (`kokoro | chatterbox | dramabox`), per-engine params
- STT: `stt_model_size` (`tiny | base | small | medium | large`), `stt_language`
- Wake word: `wake_word_model`, `wake_word_threshold`
- Voice activity: `silence_timeout_seconds`, `silence_chunks_threshold`
- Studio mode: `studio_pipeline_mode` (`cpu_stt | pause`)
- HASS: `hass_url`, `hass_token`
- Google Calendar: `gcal_credentials_file`, `gcal_calendar_id`
- Web search: `web_search_default`, `web_search_max_results`, `google_search_api_key`, `google_search_cx`
- Memory: `memory_dir` (default `~/.plia`)
- Modules: `disabled_modules` (list of module filenames to skip at load)

### Tool registry (`core/registry.py`)

`@tool("description")` decorator registers a function for LLM function-calling. Tools are auto-discovered by `load_modules()` scanning `modules/*.py`. To add a tool: create or edit a file in `modules/`, decorate the function with `@tool`. The decorator auto-generates the OpenAI-compatible JSON schema from type hints.

### Specialist agents (`agents/`)

Each agent is an async LangGraph node `async def X_node(state) -> dict`. All receive the full `AgentState` and return partial state updates.

| Agent | File | Routes from |
|-------|------|-------------|
| memory | `agents/memory.py` | "remember that", "recall what", etc. |
| web | `agents/web.py` | "search for", "look it up", etc. |
| code | `agents/code.py` | "run this code", "```python", etc. |
| calendar | `agents/calendar.py` | "add to calendar", "schedule a", etc. |
| home | `agents/home.py` | "turn on the", "lights on", etc. |
| reminder | `agents/reminder.py` | "remind me", "set a reminder", etc. |

Reminder agent parses natural-language time expressions via LLM (injects current UTC, requests ISO 8601 output), then calls `memory_store.add_reminder()`.

### MemoryStore (`agents/memory_store.py`)

Singleton via `get_memory_store()`. SQLite at `~/.plia/memory.db` with three tables:
- `facts` — key/value pairs (`remember(key, value)`, `recall_fact(key)`)
- `history` — chat turns, capped at 500 (`add_turn()`, `recall()`)
- `reminders` — `id | message | fire_at | done | is_timer`

Reminder CRUD: `add_reminder(message, fire_at_iso, is_timer=False)`, `get_pending()` (overdue only), `list_pending(timers_only=False)`, `mark_reminder_done(id)`, `prune_done_reminders(older_than_days=7)`.

ChromaDB is optional — if unavailable, semantic recall degrades to empty list (facts storage still works). All methods synchronous; wrap with `asyncio.to_thread()` in async contexts.

### Chat history (`agents/chat_history.py`)

Separate SQLite at `data/chat_history.db` (project-local, gitignored). Functions: `add_message(role, content)`, `get_recent(n=100)`, `clear()` (archives to memory_store before deleting). Used by:
- `POST /api/chat` — loads last 20 turns as context
- `voice/pipeline.py` — preloads last 20 turns on startup (`_HISTORY_PRELOAD = 20`)
- `GET /api/history`, `DELETE /api/history` dashboard endpoints

### Voice pipeline (`voice/pipeline.py`)

State machine: armed → listening → processing → speaking → armed. Runs in a single asyncio task. Constants:
- `_HISTORY_PRELOAD = 20` — turns loaded from `chat_history` on startup
- `_CONVERSATION_CAP = 40` — max non-system messages kept in-memory

Uses `get_stt_service()` (shared singleton with `/api/voice/transcribe` — loading Whisper twice wastes ~200 MB RAM). Wake word detection uses openwakeword. Audio captured as int16 (avoids PipeWire float32 normalisation issues), normalised to float32 before STT. Echo suppression: wake word muted for 4s + audio duration after TTS playback.

Announcement queue: `reminder_fired` events are queued and announced by TTS between turns.

### VRAM broker (`voice/vram_broker.py`)

`VRAMBroker` singleton via `get_vram_broker()`. Tracks GPU models (`ModelEntry`: name, priority, vram_gb, load/unload callbacks). `request(name)` loads the model, evicting lower-priority models as needed. `release(name)` unloads. Dashboard endpoints: `GET /api/vram/status`, `POST /api/vram/release`.

TTS engine hot-swap: `POST /api/config` with a new `tts_engine` triggers `svc.switch_engine()` in a background task protected by `_engine_switch_lock` (asyncio.Lock). `vram_release` also calls `switch_engine("kokoro")` under the same lock to keep config and service in sync.

### AirLLM (`agents/airllm_backend.py`)

Layer-by-layer inference for large models (~4 GB VRAM for 70B+). Enabled by setting `airllm_model` in config. Compression selectable per-model in dashboard LLM panel. Falls back to Ollama if AirLLM not configured.

### Reminder loop (`core/reminder_loop.py`)

`run_reminder_loop()` — background asyncio task, polls every 30 seconds. Calls `store.get_pending()`, emits `reminder_fired` for each overdue reminder, marks done. Prunes old done reminders on startup. Error per iteration is caught and logged; loop continues.

### Dashboard (`dashboard/server.py` + `dashboard/static/index.html`)

Single FastAPI router mounted at `/`. WebSocket at `/ws` relays all `core.events` payloads to connected browser clients. `index.html` is a self-contained SPA — all JS is inline. Config is loaded once on page load via `GET /api/config` and saved field-by-field via `POST /api/config`. When adding a new config field to the UI: (1) add HTML controls, (2) add to the relevant `apply*()` function payload, (3) populate in the `fetch('/api/config').then(cfg => {...})` block.

Dashboard panels: Voice/TTS config, LLM (AirLLM + compression), Calendar, HASS entities, Memory viewer, System stats (CPU/RAM/GPU), Pipeline status badge, Reminders, Browser voice input.

### Testing patterns

`conftest.py` has three `autouse` fixtures that run for every test:
- `isolate_config_file` — redirects `_CONFIG_FILE` to a temp path (tests never touch `~/.plia/`)
- `reset_registry` — clears tool registrations before/after each test
- `reset_events` — clears event subscribers before/after each test

API endpoint tests use `httpx.AsyncClient(transport=ASGITransport(app=create_app()))`. Mock the LLM with `respx` or patch `agents.llm.call_llm`. Mock MemoryStore methods with `unittest.mock.patch("agents.memory_store.get_memory_store", return_value=mock)`. Mock `agents.chat_history.get_recent` for pipeline history preload tests.
