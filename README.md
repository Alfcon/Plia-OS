# Plia-OS

A local AI voice assistant with a web dashboard and a multi-agent backend.

## How it works

1. **Wake word** — openwakeword listens for the wake phrase
2. **STT** — faster-whisper transcribes speech to text
3. **Agents** — a LangGraph supervisor routes the request to specialist agents (memory, web, code, calendar, home)
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
pip install -e .
```

Or use the pinned lockfile:

```bash
pip install -r requirements.txt
pip install -e . --no-deps
```

Optional extras:

```bash
pip install -e ".[playwright]"          # web scraping
pip install -e ".[fallback-openai]"     # OpenAI fallback LLM
pip install -e ".[fallback-anthropic]"  # Anthropic fallback LLM
pip install -e ".[dramabox]"            # Dramabox TTS engine
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
| ☰ Menu → Voice | TTS engine, voice cloning, clip generation |
| ☰ Menu → Web | Web search provider and Google API keys |
| ☰ Menu → LLM | Fallback cloud LLM provider and model |
| ☰ Menu → Agents | Live agent routing badges and log |
| ☰ Menu → System | Registered tool modules list |
| ☰ Exit | Graceful shutdown via SIGTERM |

## Agents

| Agent | What it does |
|-------|-------------|
| memory | Remembers and recalls facts (SQLite + ChromaDB) |
| web | Searches via DuckDuckGo, Google Custom Search, or Playwright scrape |
| code | Runs Python/shell in a sandboxed subprocess |
| calendar | Add, list, delete events in `~/.plia/calendar.ics` |
| home | Smart home stub (not yet implemented) |

## TTS Engines

| Engine | VRAM | Notes |
|--------|------|-------|
| Kokoro | ~0.4 GB | Default; fast, high quality |
| Chatterbox | ~2 GB | Voice cloning with reference audio |
| Dramabox | ~8.5 GB | Expressive long-form narration |

VRAM broker evicts lower-priority models automatically when switching engines.

## Chat History

All conversations persist to `data/chat_history.db` (SQLite). Loaded on every page refresh. Clear via the ✕ button in the input bar or `DELETE /api/history`.

## Configuration

All config in `core/config.py` as a `PliaConfig` dataclass. Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |
| `ollama_model` | `llama3.2` | Model for inference |
| `tts_engine` | `kokoro` | TTS engine: `kokoro`, `chatterbox`, `dramabox` |
| `stt_model_size` | `base` | Whisper model size |
| `wake_word_model` | `hey_jarvis` | Wake word (or path to custom `.onnx`) |
| `web_search_default` | `ddg` | Default search provider |
| `fallback_provider` | _(empty)_ | Cloud fallback: `openai` or `anthropic` |
| `memory_dir` | `~/.plia` | Memory DB and calendar ICS location |

Settings can be changed live from the dashboard without restarting.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | Get current config |
| POST | `/api/config` | Update config fields |
| GET | `/api/history` | Get chat history (param: `n=100`) |
| DELETE | `/api/history` | Clear chat history |
| POST | `/api/chat` | Send a text message to the agent |
| GET | `/api/system/info` | OS, CPU, RAM, VRAM, disk metrics |
| GET | `/api/system/capabilities` | Per-engine VRAM fit check |
| GET | `/api/vram/status` | Current VRAM broker state |
| POST | `/api/vram/release` | Release a loaded model |
| POST | `/api/generate-chatterbox` | Synthesise a WAV clip (Chatterbox) |
| POST | `/api/generate-dramabox` | Synthesise a WAV clip (Dramabox) |
| POST | `/api/shutdown` | Graceful shutdown |
| WS | `/ws` | Live events (status, transcript, agent_routing, vram_status) |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

172 tests, all passing.
