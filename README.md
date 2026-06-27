# Plia-OS

A local AI voice assistant with a web dashboard and a multi-agent backend.

## How it works

1. **Wake word** — openwakeword listens for the wake phrase
2. **STT** — faster-whisper transcribes speech to text
3. **Agents** — a LangGraph supervisor routes the request to specialist agents
4. **TTS** — Kokoro, Chatterbox, or Dramabox speaks the response
5. **Dashboard** — full-width top bar with system metrics, menu-based settings, persistent chat history

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally with a model loaded (default: `llama3.2`)
- A microphone

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e . --no-deps
```

`requirements.txt` includes all optional extras (cloud fallbacks, AirLLM, observer, MCP). To install only the core:

```bash
pip install -e .
```

Optional extras (install individually as needed):

```bash
pip install -e ".[playwright]"          # web scraping
pip install -e ".[fallback-openai]"     # OpenAI fallback LLM
pip install -e ".[fallback-anthropic]"  # Anthropic fallback LLM
pip install -e ".[dramabox]"            # Dramabox TTS engine
pip install -e ".[airllm]"              # AirLLM (70B+ on 4 GB VRAM)
pip install -e ".[mcp]"                 # Model Context Protocol servers
pip install -e ".[tor]"                 # Tor network routing
pip install -e ".[observer]"            # Screen/keyboard activity tracking
pip install -e ".[dev]"                 # Test dependencies
```

## Run

```bash
python core/main.py
```

Dashboard at `http://localhost:8000`. Voice pipeline starts automatically; dashboard stays available even if pipeline fails to load.

## Dashboard

| Area | What's there |
|------|-------------|
| Top bar | Status badge, OS, CPU %, RAM, VRAM bar (clickable), Disk |
| Chat pane | Persistent conversation history, text input (Enter to send) |
| ☰ Menu → Voice | TTS engine, STT model, wake word, voice cloning, clip generation |
| ☰ Menu → LLM | Ollama model, AirLLM, compression, fallback cloud provider |
| ☰ Menu → Web | Web search provider and Google API keys |
| ☰ Menu → Agents | Live agent routing badges and log |
| ☰ Menu → System | CPU/RAM/GPU stats, tool modules list |
| ☰ Menu → Reminders | Pending reminders and timers |
| ☰ Menu → Calendar | Upcoming events, Google Calendar link |
| ☰ Menu → Memory | Stored facts viewer and search |
| ☰ Menu → History | Conversation history viewer with search and expand |
| ☰ Menu → Modules | Enable/disable tool modules |
| ☰ Menu → MCP | Model Context Protocol server config |
| ☰ Menu → Home | Home Assistant entity list and toggles |
| ☰ Menu → Permissions | Per-tool execution approval settings |
| ☰ Menu → Network | MAC randomisation, Tor routing |
| ☰ Menu → Cron | Scheduled proactive tasks |
| ☰ Menu → Tokens | LLM token usage and cost tracking |
| ☰ Menu → Email | IMAP account management, connection test |
| ☰ Menu → Observer | Live app tracker, focus timeline, activity profile |
| ☰ Menu → Proactive | Proactive assistant enable/disable, quiet hours |
| ☰ Exit | Graceful shutdown via SIGTERM |

## Agents

| Agent | What it does |
|-------|-------------|
| memory | Remembers and recalls facts (SQLite + ChromaDB) |
| web | Searches via DuckDuckGo, Google Custom Search, or Playwright scrape |
| code | Runs Python/shell in a sandboxed subprocess |
| calendar | Add, list, delete events in `~/.plia/calendar.ics` or Google Calendar |
| reminder | Persists reminders to SQLite, fires as dashboard notifications via background polling |
| home | Calls Home Assistant services and reads entity states |
| file | Reads, writes, lists, and searches local files |
| network | MAC randomisation, Tor routing, Wi-Fi scanning |
| weather | Current conditions and forecast via Open-Meteo |

## TTS Engines

| Engine | VRAM | Notes |
|--------|------|-------|
| Kokoro | ~0.4 GB | Default; fast, high quality |
| Chatterbox | ~2 GB | Voice cloning with reference audio |
| Dramabox | ~8.5 GB | Expressive long-form narration |

VRAM broker evicts lower-priority models automatically when switching engines.

## Chat History

All conversations persist to `data/chat_history.db` (SQLite). Loaded on every page refresh. The voice pipeline also reloads the last 20 messages on startup so context survives restarts. Clear via the ✕ button in the input bar or `DELETE /api/history`.

## Reminders

The `set_reminder` tool (available to the LLM) persists reminders to SQLite. A background loop polls every 30 seconds and fires overdue reminders as dashboard notifications via the WebSocket. Reminders survive restarts.

## Observer

When enabled, tracks foreground app focus durations and (optionally) screen OCR and keystrokes. Data stored in `~/.plia/observer.db`. Dashboard shows live current app, top-apps bar chart, focus timeline, and an AI-generated activity profile.

## Email

IMAP accounts configured in the dashboard (☰ Menu → Email). Each account has a **Test** button to verify connectivity without fetching messages (uses the IMAP STATUS command — fast even on large inboxes). Used by the morning briefing to surface unread counts.

## Proactive Assistant

Background loop (configurable interval) that monitors memory, reminders, observer data, and email to surface proactive suggestions. Respects quiet hours. Managed via ☰ Menu → Proactive or `POST /api/proactive/enable`.

## Configuration

All config in `core/config.py` as a `PliaConfig` dataclass, persisted to `~/.plia/config.json`. Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |
| `ollama_model` | `llama3.2` | Model for inference |
| `tts_engine` | `kokoro` | TTS engine: `kokoro`, `chatterbox`, `dramabox` |
| `stt_model_size` | `base` | Whisper model size |
| `wake_word_model` | `hey_jarvis` | Wake word (or path to custom `.onnx`) |
| `web_search_default` | `ddg` | Default search provider: `ddg`, `google` |
| `fallback_provider` | _(empty)_ | Cloud fallback: `openai` or `anthropic` |
| `airllm_model` | _(empty)_ | HuggingFace model ID for AirLLM |
| `airllm_compression` | `4bit` | AirLLM compression: `4bit`, `8bit`, `none` |
| `hass_url` | _(empty)_ | Home Assistant base URL |
| `hass_token` | _(empty)_ | Home Assistant long-lived access token |
| `gcal_credentials_file` | _(empty)_ | Path to Google OAuth credentials JSON |
| `observer_enabled` | `false` | Enable activity observer |
| `memory_dir` | `~/.plia` | Memory DB, calendar ICS, and observer DB location |
| `disabled_modules` | `[]` | Module filenames to skip at load |

Settings can be changed live from the dashboard without restarting.

## API Endpoints

### Config & System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | Current config |
| POST | `/api/config` | Update config fields |
| GET | `/api/system/info` | OS, CPU, RAM, VRAM, disk metrics |
| GET | `/api/system/capabilities` | Per-engine VRAM fit check |
| GET | `/api/modules` | Loaded tool modules |
| POST | `/api/modules/{name}/enable` | Enable a module |
| POST | `/api/modules/{name}/disable` | Disable a module |
| GET | `/api/tools` | Registered tools list |
| GET | `/api/tools/schemas` | Full tool JSON schemas |
| POST | `/api/tools/run` | Run a tool by name |
| GET | `/api/permissions` | Per-tool permission settings |
| POST | `/api/permissions/tools` | Update tool permissions |
| GET | `/api/token-usage` | LLM token usage and cost |
| POST | `/api/token-usage/reset` | Reset token counters |

### Chat & History
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a text message to the agent |
| GET | `/api/history` | Chat history (`?n=100`) |
| DELETE | `/api/history` | Clear chat history |

### Voice & Pipeline
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipeline/status` | Voice pipeline state |
| POST | `/api/pipeline/start` | Start voice pipeline |
| POST | `/api/pipeline/stop` | Stop voice pipeline |
| POST | `/api/voice/transcribe` | Transcribe audio upload |
| POST | `/api/start-recording` | Start browser mic recording |
| POST | `/api/stop-recording` | Stop browser mic recording |
| POST | `/api/upload-reference-audio` | Upload voice clone reference |
| POST | `/api/generate-chatterbox` | Synthesise WAV (Chatterbox) |
| POST | `/api/generate-dramabox` | Synthesise WAV (Dramabox) |

### Memory & Notes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory` | List stored facts |
| GET | `/api/memory/search` | Search facts (`?q=`) |
| POST | `/api/memory` | Store a fact |
| PUT | `/api/memory/{key}` | Update a fact |
| DELETE | `/api/memory/{key}` | Delete a fact |
| GET | `/api/notes` | List notes |
| POST | `/api/notes` | Create a note |
| PUT | `/api/notes/{key}` | Update a note |
| DELETE | `/api/notes/{key}` | Delete a note |

### Reminders & Cron
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/reminders` | List pending reminders |
| POST | `/api/reminders` | Create a reminder |
| DELETE | `/api/reminders/{id}` | Delete a reminder |
| GET | `/api/timers` | List active timers |
| DELETE | `/api/timers/{id}` | Delete a timer |
| GET | `/api/cron` | List cron jobs |
| POST | `/api/cron` | Create a cron job |
| PATCH | `/api/cron/{name}` | Update a cron job |
| DELETE | `/api/cron/{name}` | Delete a cron job |

### Calendar
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/calendar` | List events |
| POST | `/api/calendar` | Create an event |
| DELETE | `/api/calendar/{uid}` | Delete an event |
| GET | `/api/calendar/google/status` | Google Calendar auth state |
| POST | `/api/calendar/google/auth` | Start Google OAuth flow |
| GET | `/api/calendar/google/callback` | Google OAuth callback |

### Email
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/email/accounts` | List email accounts |
| POST | `/api/email/accounts` | Add an email account |
| DELETE | `/api/email/accounts/{name}` | Remove an email account |
| POST | `/api/email/accounts/{name}/test` | Test IMAP connectivity |
| POST | `/api/email/accounts/{name}/auth` | Start Gmail OAuth flow |
| GET | `/api/email/accounts/{name}/callback` | Gmail OAuth callback |
| GET | `/api/email/accounts/{name}/status` | Gmail OAuth status |

### Home Assistant & VRAM
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hass/entities` | List HASS entities |
| POST | `/api/hass/toggle/{entity_id}` | Toggle entity |
| GET | `/api/vram/status` | VRAM broker state |
| POST | `/api/vram/release` | Release a loaded model |

### System Prompt
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/system-prompt/undo` | Revert system prompt |
| POST | `/api/system-prompt/reset` | Reset to default |

### Observer & Proactive
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/observer/status` | Observer state and profile preview |
| POST | `/api/observer/enable` | Enable observer |
| POST | `/api/observer/disable` | Disable observer |
| GET | `/api/observer/activity` | Top apps, timeline, profile (`?minutes=60`) |
| GET | `/api/proactive/status` | Proactive assistant state |
| POST | `/api/proactive/enable` | Enable proactive loop |
| POST | `/api/proactive/disable` | Disable proactive loop |

### Tor & Tool Guard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tor/status` | Tor routing state |
| POST | `/api/tor/enable` | Enable Tor |
| POST | `/api/tor/disable` | Disable Tor |
| POST | `/api/tool-guard/respond/{id}` | Approve/deny a pending tool call |

### MCP
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mcp/servers` | Connected MCP servers |
| GET | `/api/mcp/config` | MCP server config |
| PUT | `/api/mcp/config` | Update MCP server config |
| POST | `/api/mcp/restart` | Restart MCP connections |
| POST | `/api/mcp/servers/{name}/disable` | Disable an MCP server |

### WebSocket
| Method | Path | Description |
|--------|------|-------------|
| WS | `/ws` | Live events: `status`, `transcript`, `agent_routing`, `vram_status`, `reminder_fired`, `tool_guard_request`, `proactive_message` |

### Shutdown
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/shutdown` | Graceful shutdown |

## Tests

```bash
pip install -e ".[dev]"
pytest
pytest --tb=short -q          # terse output
pytest tests/test_foo.py -v   # single file
```

923 tests, all passing.
