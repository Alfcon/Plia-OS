# Plia-OS

A local AI voice assistant with a web dashboard and a multi-agent backend.

## How it works

1. **Wake word** — openwakeword listens for the wake phrase
2. **STT** — faster-whisper transcribes speech to text
3. **Agents** — a LangGraph supervisor routes the request to specialist agents
4. **TTS** — Kokoro, Chatterbox, or Dramabox speaks the response
5. **Dashboard** — full-width top bar with system metrics, media controls, menu-based settings, persistent chat history

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
| Top bar | Status badge, OS, CPU %, RAM, VRAM bar (clickable), Disk, **media player** (track, ⏮▶⏭, volume) |
| Chat pane | Persistent conversation history, text input (Enter to send, Shift+Enter for newline) |
| ☰ Menu → Voice | TTS engine, STT model, wake word, voice cloning, clip generation |
| ☰ Menu → LLM | Ollama model, AirLLM model picker + VRAM estimate, compression, fallback cloud provider, system prompt |
| ☰ Menu → Web | Web search provider and Google API keys |
| ☰ Menu → Agents | Live agent routing badges and log |
| ☰ Menu → System | CPU/RAM/GPU stats, pipeline start/stop, config export/import, tool modules list |
| ☰ Menu → Reminders | Pending reminders and timers |
| ☰ Menu → Calendar | Upcoming events, Google Calendar link |
| ☰ Menu → Memory | Stored facts viewer, search, notes |
| ☰ Menu → History | Conversation history viewer with search and expand |
| ☰ Menu → Modules | Enable/disable tool modules |
| ☰ Menu → MCP | Model Context Protocol server config |
| ☰ Menu → Home | Home Assistant entity list and toggles |
| ☰ Menu → Permissions | Per-tool execution approval, tool guard list |
| ☰ Menu → News | DDG news search by topic, RSS feed reader |
| ☰ Menu → Network | Tor toggle, WiFi scan (signal/security/channel), MAC randomise/restore |
| ☰ Menu → Cron | Scheduled tasks with presets, next-run display, `tool:` invocation |
| ☰ Menu → Tokens | LLM token usage and cost tracking |
| ☰ Menu → Briefing | Morning briefing config: section toggles, time, preview button |
| ☰ Menu → Docs | Document index: index directories, search chunks, manage sources |
| ☰ Menu → Email | IMAP account management, Gmail OAuth, connection test |
| ☰ Menu → Observer | Live app tracker, focus timeline, activity profile |
| ☰ Menu → Proactive | Proactive assistant enable/disable, quiet hours |
| 🔧 Tools | Run any registered tool directly with auto-generated param inputs and full output |
| ☰ Exit | Graceful shutdown via SIGTERM |
| `?` key | Keyboard shortcuts overlay |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus chat input |
| `Enter` | Send message |
| `Shift+Enter` | New line in message |
| `Ctrl+K` | Open Tools panel |
| `Ctrl+,` | Open Settings panel |
| `Esc` | Close open panel |
| `Enter` | Allow tool call (tool guard modal) |
| `Esc` | Deny tool call (tool guard modal) |
| `?` | Keyboard shortcuts overlay |

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

## Cron

Recurring scheduled tasks stored in `~/.plia/cron.db`. Messages can be plain text (announced via TTS) or `tool:tool_name` to invoke any registered tool directly. Dashboard shows next-run time relative to now. Expression presets available (Daily 8am, Weekdays 8am, Hourly, etc.).

## Document Index

`index_documents(directory, glob)` chunks files and stores embeddings in ChromaDB at `~/.plia/doc_index`. Supports `.txt`, `.md`, `.pdf`, `.docx`, `.json`, `.yaml`, `.csv`. Search via `query_documents(query)`. Manage indexed sources from ☰ Menu → Docs.

## Observer

When enabled, tracks foreground app focus durations and (optionally) screen OCR and keystrokes. Data stored in `~/.plia/observer.db`. Dashboard shows live current app, top-apps bar chart, focus timeline, and an AI-generated activity profile.

## Email

IMAP accounts configured in the dashboard (☰ Menu → Email). Each account has a **Test** button to verify connectivity without fetching messages (uses the IMAP STATUS command — fast even on large inboxes). Used by the morning briefing to surface unread counts.

## Morning Briefing

`morning_briefing()` tool assembles a spoken briefing from configurable sections: weather, today's reminders, calendar events, email unread counts, and news headlines. Configure from ☰ Menu → Briefing: choose sections, set news topic, location, and daily schedule time. **Preview** button runs the briefing live in the panel.

## Proactive Assistant

Background loop (configurable interval) that monitors memory, reminders, observer data, and email to surface proactive suggestions. Respects quiet hours. Managed via ☰ Menu → Proactive or `POST /api/proactive/enable`.

## AirLLM

Layer-by-layer inference for large models (~4 GB VRAM for 70B+). Configure from ☰ Menu → LLM → AirLLM: pick a HuggingFace model ID (autocomplete with 15 popular models), select compression (4bit/8bit/none), see live VRAM estimate, and apply. Unload button frees VRAM on demand.

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
| `weather_location` | _(empty)_ | Default location for weather (e.g. `Berlin`) |
| `briefing_news_topic` | `breaking news` | News topic for morning briefing |
| `briefing_cron_enabled` | `false` | Auto-deliver briefing daily |
| `briefing_cron_time` | `07:00` | Daily briefing time (HH:MM) |
| `briefing_include_weather` | `true` | Include weather in briefing |
| `briefing_include_reminders` | `true` | Include reminders in briefing |
| `briefing_include_calendar` | `true` | Include calendar in briefing |
| `briefing_include_email` | `true` | Include email counts in briefing |
| `briefing_include_news` | `true` | Include news headlines in briefing |
| `tool_guard_list` | `[]` | Tools requiring user approval before execution |
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
| POST | `/api/tools/run` | Run a tool by name with params |
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
| GET | `/api/cron` | List cron jobs (includes `next_run`) |
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

### Documents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents/sources` | List indexed document sources |
| POST | `/api/documents/index` | Index a directory (`{directory, glob}`) |
| POST | `/api/documents/remove` | Remove a source (`{source}`) |
| POST | `/api/documents/search` | Semantic search (`{query, n_results}`) |

### News
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/news/search` | DDG news search (`{query, max_items}`) |
| POST | `/api/news/rss` | Fetch and parse RSS feed (`{url, max_items}`) |

### Media & Audio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/media/status` | Now-playing track and playback state |
| POST | `/api/media/{action}` | Transport control: `play`, `pause`, `next`, `previous`, `stop` |
| GET | `/api/media/volume` | Current volume and mute state |
| POST | `/api/media/volume` | Set volume (`{percent}`) |
| POST | `/api/media/mute` | Mute audio |
| POST | `/api/media/unmute` | Unmute audio |

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

### Network
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/network/wifi` | WiFi scan + current connection |
| GET | `/api/network/mac` | List network interface MACs |
| POST | `/api/network/mac/randomize` | Randomize MAC address |
| POST | `/api/network/mac/restore` | Restore original MAC address |

### Home Assistant & VRAM
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hass/entities` | List HASS entities |
| POST | `/api/hass/toggle/{entity_id}` | Toggle entity |
| GET | `/api/vram/status` | VRAM broker state |
| POST | `/api/vram/release` | Release a loaded model |

### AirLLM
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/airllm/status` | AirLLM load state and model ID |
| POST | `/api/airllm/unload` | Unload AirLLM model from VRAM |

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

935 tests, all passing.
